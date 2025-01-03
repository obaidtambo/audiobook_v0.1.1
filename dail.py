import json
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import List
import re
from datetime import datetime
from typing import List, Tuple

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from langchain_core.messages import AIMessage

database='DBS/dialogue_analysis.db'
# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Pydantic model for dialogue validation
class Dialogue(BaseModel):
    speaker: str
    content: str
    tone: str

def setup_databases():
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS dialogues (
        id TEXT PRIMARY KEY,
        chain_id TEXT,
        book_id TEXT,
        page_number INTEGER,
        speaker TEXT,
        content TEXT,
        tone TEXT,
        extraction_method TEXT,
        validation_status TEXT,
        created_at TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chain_steps (
        id TEXT PRIMARY KEY,
        chain_id TEXT,
        step_name TEXT,
        step_data JSON,
        status TEXT,
        created_at TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

class DialogueAnalysisPipeline:
    def __init__(self, model_name="gpt-4o-mini", temperature=0.5):
        self.llm = ChatOpenAI(model_name=model_name, temperature=temperature)
        
        # Initial extraction chain with improved prompt
        self.extraction_chain = (
            ChatPromptTemplate.from_messages([
                ("system", """
                Extract dialogues from the text below. For each dialogue provide:
                - The character speaking
                - The actual dialogue content
                - The tone/emotion of the dialogue

                If there are no dialogues in the text (no direct speech or quotes), 
                return an empty list: []
                
                Text: {text}
                
                Return a list of dialogues in this exact format:
                [
                    {{
                        "speaker": "character name",
                        "content": "the actual dialogue",
                        "tone": "emotional tone of speech"
                    }}
                ]
                
                Remember:
                - Only extract text within quotation marks
                - If no dialogues are found, return []
                - Ensure you return ONLY the JSON list, nothing else
                """),
                ("user", "{text}")
            ])
            | self.llm
            | RunnablePassthrough()
        )
        
        # Parser chain for fixing invalid formats
        self.parser_chain = (
            ChatPromptTemplate.from_messages([
                ("system", """
                Parse the following text into a list of dialogues. 
                If no dialogues are present (no quoted speech), return an empty list: []
                
                Convert any found dialogues to this exact JSON format:
                [
                    {{
                        "speaker": "character name",
                        "content": "the actual dialogue",
                        "tone": "emotional tone of speech"
                    }}
                ]
                
                Text to parse: {text}
                
                Return ONLY the JSON list, no other text.
                If no dialogues found, return just: []
                """),
                ("user", "{text}")
            ])
            | self.llm
            | RunnablePassthrough()
        )
        
        setup_databases()
    
    def _log_debug(self, step: str, data: any):
        logger.debug(f"{step}:\n{json.dumps(data, indent=2)}\n{'='*50}")

    def _save_chain_step(self, chain_id: str, step_name: str, step_data: dict, status: str):
        try:
            if isinstance(step_data.get("output"), AIMessage):
                step_data_dict = {
                    "content": step_data["output"].content,
                    "additional_kwargs": step_data["output"].additional_kwargs,
                    "response_metadata": step_data["output"].response_metadata
                }
            else:
                step_data_dict = step_data
            
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            
            step_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO chain_steps (id, chain_id, step_name, step_data, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (step_id, chain_id, step_name, json.dumps(step_data_dict), status, datetime.now())
            )
            
            conn.commit()
            conn.close()
            
            self._log_debug(f"Chain Step: {step_name}", {
                "step_id": step_id,
                "chain_id": chain_id,
                "status": status,
                "data": step_data_dict
            })
            
        except Exception as e:
            logger.error(f"Error saving chain step: {str(e)}")
            
    def _save_dialogue(self, chain_id: str, book_id: str, page_number: int, 
                      dialogue_data: dict, extraction_method: str, validation_status: str):
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        dialogue_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO dialogues 
               (id, chain_id, book_id, page_number, speaker, content, tone,
                extraction_method, validation_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dialogue_id,
                chain_id,
                book_id,
                page_number,
                dialogue_data['speaker'],
                dialogue_data['content'],
                dialogue_data['tone'],
                extraction_method,
                validation_status,
                datetime.now()
            )
        )
        
        conn.commit()
        conn.close()
        
        self._log_debug("Saved Dialogue", {
            "dialogue_id": dialogue_id,
            "chain_id": chain_id,
            "data": dialogue_data
        })

    def _validate_dialogue(self, dialogue_data: dict) -> bool:
        try:
            Dialogue(**dialogue_data)
            return True
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return False

    def _parse_json_result(self, text: str) -> List[dict]:
        """Attempt to parse the extraction result into a list of dialogue dictionaries"""
        try:
            # First, ensure we have valid JSON by stripping any whitespace
            text = text.strip()
            if text == "[]":  # Handle empty list case explicitly
                return []
                
            result = json.loads(text)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "dialogues" in result:
                return result["dialogues"]
            else:
                raise ValueError("Unexpected JSON structure")
        except Exception as e:
            logger.error(f"Parsing error: {str(e)}")
            return None

    def _extract_narrator_text(self, full_text: str, dialogues: List[dict]) -> List[Tuple[str, int]]:

        """
        Extract narrator text from the full text by removing known character dialogues.
        
        Args:
            full_text (str): The complete text of the story
            character_dialogues (list[dict]): List of dictionaries containing speaker and dialogue pairs
            
        Returns:
            list[dict]: List of dictionaries with narrator text segments
        """
        # Create a copy of the text to mark dialogue positions
        working_text = full_text
        
        # Sort dialogues by their position in the text
        dialogue_positions = []
        for dialogue_info in dialogues:
            dialogue = dialogue_info['content']
            # Find the dialogue in the text (including quotation marks)
            quoted_dialogue = f'"{dialogue}"'
            start = working_text.find(quoted_dialogue)
            if start != -1:
                end = start + len(quoted_dialogue)
                dialogue_positions.append((start, end))
        
        # Sort positions by start index
        dialogue_positions.sort()
        
        # Extract narrator segments
        narrator_segments = []
        current_pos = 0
        
        for start, end in dialogue_positions:
            # Get text before dialogue
            if current_pos < start:
                narrator_text = working_text[current_pos:start].strip()
                if narrator_text:  # Only add non-empty segments
                    narrator_segments.append({
                        "speaker": "Narrator",
                        "content": narrator_text
                    })
            current_pos = end
        
        # Add final segment after last dialogue
        if current_pos < len(working_text):
            final_text = working_text[current_pos:].strip()
            if final_text:  # Only add non-empty segments
                narrator_segments.append({
                    "speaker": "Narrator",
                    "content": final_text
                })
        
        return narrator_segments

        # """
        # Extract narrator text between dialogues and split it into segments.
        # Returns list of (text, position) tuples.
        # """
        # # Create a list of all dialogue positions
        # dialogue_positions = []
        # for dialogue in dialogues:
        #     content = dialogue['content']
        #     start = full_text.find(f'"{content}"')
        #     if start != -1:
        #         end = start + len(f'"{content}"')
        #         dialogue_positions.append((start, end))
        
        # # Sort positions by start index
        # dialogue_positions.sort()
        
        # # Extract narrator text between dialogues
        # narrator_segments = []
        # current_pos = 0
        
        # for start, end in dialogue_positions:
        #     # Get text before dialogue
        #     if current_pos < start:
        #         narrator_text = full_text[current_pos:start].strip()
        #         if narrator_text:
        #             narrator_segments.append((narrator_text, current_pos))
        #     current_pos = end
        
        # # Get final text after last dialogue
        # if current_pos < len(full_text):
        #     narrator_text = full_text[current_pos:].strip()
        #     if narrator_text:
        #         narrator_segments.append((narrator_text, current_pos))
        
        # return narrator_segments

    def _process_narrator_segments(self, chain_id: str, narrator_segments: List[Tuple[str, int]]) -> List[dict]:
        """Process narrator segments and return them in dialogue format"""
        narrator_dialogues = []
        i=0
        for info in narrator_segments:
            try:
                # Analyze tone of narrator text
                # analysis_result = self.narrator_analysis_chain.invoke({"text": text})
                # tone_data = json.loads(analysis_result.content)
                
                narrator_dialogue = {
                    "speaker": info["speaker"],
                    "content": info['content'],
                    "tone": 'neutral'
                }
                
                narrator_dialogues.append(narrator_dialogue)
                
                self._save_chain_step(
                    chain_id,
                    f"narrator_analysis_{i}",
                    {"text": info['content'], "analysis": 'Hardcoded @obaidtamboli'},
                    "completed"
                )
                i=i+1
                
            except Exception as e:
                logger.error(f"Error processing narrator segment: {str(e)}")
                self._save_chain_step(
                    chain_id,
                    f"narrator_analysis_{i}",
                    {"error": str(e)},
                    "failed"
                )
        
        return narrator_dialogues

    def analyze(self, text: str, book_id: str, page_number: int, max_retries: int = 3) -> str:
        chain_id = str(uuid.uuid4())
        logger.info(f"Starting dialogue analysis with chain_id: {chain_id}")
        
        # Step 1: Initial dialogue extraction (remains the same)
        extraction_result = self.extraction_chain.invoke({"text": text})
        self._save_chain_step(chain_id, "initial_extraction", 
                            {"output": extraction_result}, "completed")
        
        dialogues = self._parse_json_result(extraction_result.content)
        extraction_method = "primary"
        
        # Retry with parser chain if needed (remains the same)
        if dialogues is None:
            logger.info("Initial parsing failed, attempting parser chain")
            extraction_method = "parser"
            for attempt in range(max_retries):
                parser_result = self.parser_chain.invoke({"text": extraction_result.content})
                self._save_chain_step(chain_id, f"parser_attempt_{attempt}", 
                                    {"output": parser_result}, "completed")
                
                dialogues = self._parse_json_result(parser_result.content)
                if dialogues is not None:
                    break
                extraction_result = parser_result.content

        if dialogues is None:
            error_msg = "Failed to parse dialogue data after all attempts"
            self._save_chain_step(chain_id, "error", {"error": error_msg}, "failed")
            raise ValueError(error_msg)
        
        # Step 2: Extract and process narrator text
        narrator_segments = self._extract_narrator_text(text, dialogues or [])
        narrator_dialogues = self._process_narrator_segments(chain_id, narrator_segments)
        
        self._save_chain_step(
            chain_id,
            "narrator_extraction",
            {"segments_count": len(narrator_dialogues)},
            "completed"
        )
        
        # Save all dialogues (character and narrator)
        all_dialogues = dialogues + narrator_dialogues
        
        for dialogue in all_dialogues:
            is_valid = self._validate_dialogue(dialogue)
            validation_status = "valid" if is_valid else "invalid"
            
            self._save_dialogue(
                chain_id=chain_id,
                book_id=book_id,
                page_number=page_number,
                dialogue_data=dialogue,
                extraction_method=extraction_method,
                validation_status=validation_status
            )
            
            self._save_chain_step(
                chain_id,
                "validation",
                {
                    "speaker": dialogue["speaker"],
                    "validation_status": validation_status
                },
                "completed"
            )
        
        return chain_id


    # def analyze(self, text: str, book_id: str, page_number: int, max_retries: int = 3) -> str:
    #     chain_id = str(uuid.uuid4())
    #     logger.info(f"Starting dialogue analysis with chain_id: {chain_id}")
        
    #     # Step 1: Initial extraction
    #     extraction_result = self.extraction_chain.invoke({"text": text})
    #     self._save_chain_step(chain_id, "initial_extraction", 
    #                         {"output": extraction_result}, "completed")
        
    #     # Try to parse the initial extraction
    #     dialogues = self._parse_json_result(extraction_result.content)
    #     extraction_method = "primary"
        
    #     # If parsing fails, try the parser chain
    #     if dialogues is None:  # Only retry if parsing failed, not if empty list
    #         logger.info("Initial parsing failed, attempting parser chain")
    #         extraction_method = "parser"
    #         for attempt in range(max_retries):
    #             parser_result = self.parser_chain.invoke({"text": extraction_result.content})
    #             self._save_chain_step(chain_id, f"parser_attempt_{attempt}", 
    #                                 {"output": parser_result}, "completed")
                
    #             dialogues = self._parse_json_result(parser_result.content)
    #             if dialogues is not None:  # Break if we get either valid list or empty list
    #                 break
    #             extraction_result = parser_result.content

    #     if dialogues is None:  # Only fail if parsing failed completely
    #         error_msg = "Failed to parse dialogue data after all attempts"
    #         self._save_chain_step(chain_id, "error", {"error": error_msg}, "failed")
    #         raise ValueError(error_msg)
        
    #     # Handle empty dialogues case
    #     if len(dialogues) == 0:
    #         self._save_chain_step(
    #             chain_id,
    #             "no_dialogues",
    #             {"message": "No dialogues found in text"},
    #             "completed"
    #         )
    #         return chain_id
        
    #     # Validate and save each dialogue
    #     for dialogue in dialogues:
    #         is_valid = self._validate_dialogue(dialogue)
    #         validation_status = "valid" if is_valid else "invalid"
            
    #         self._save_dialogue(
    #             chain_id=chain_id,
    #             book_id=book_id,
    #             page_number=page_number,
    #             dialogue_data=dialogue,
    #             extraction_method=extraction_method,
    #             validation_status=validation_status
    #         )
            
    #         self._save_chain_step(
    #             chain_id,
    #             "validation",
    #             {
    #                 "speaker": dialogue["speaker"],
    #                 "validation_status": validation_status
    #             },
    #             "completed"
    #         )
        
    #     return chain_id

# Example usage
if __name__ == "__main__":
    pipeline = DialogueAnalysisPipeline()
    
    # Test with no dialogues
    sample_text_no_dialogue = """
    In the quiet village, Sarah the wise healer tended to the sick with her gentle touch 
    and vast knowledge of herbs. Meanwhile, John, a gruff but loyal blacksmith, worked 
    tirelessly at his forge, teaching his young apprentice Michael the secrets of metalworking.
    """
    
    # Test with dialogues
    sample_text_with_dialogue = """
    "I can't believe what we've discovered," whispered Professor Smith, his voice trembling with excitement.
    Sarah laughed and said, "You always say that about every new finding!"
    """
    
    try:
        # Test both cases
        print("\nTesting text without dialogues:")
        chain_id1 = pipeline.analyze(
            text=sample_text_no_dialogue,
            book_id="book1234",
            page_number=42
        )
        
        print("\nTesting text with dialogues:")
        chain_id2 = pipeline.analyze(
            text=sample_text_with_dialogue,
            book_id="book1234",
            page_number=43
        )
        
        # Print results for both
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        for chain_id in [chain_id1, chain_id2]:
            print(f"\nResults for chain {chain_id}:")
            
            print("Dialogues:")
            cursor.execute("""
                SELECT speaker, content, tone, validation_status 
                FROM dialogues 
                WHERE chain_id = ?
            """, (chain_id,))
            
            rows = cursor.fetchall()
            if not rows:
                print("No dialogues found")
            else:
                for row in rows:
                    print(f"\nSpeaker: {row[0]}")
                    print(f"Content: '{row[1]}'")
                    print(f"Tone: {row[2]}")
                    print(f"Status: {row[3]}")
            
            print("\nChain Steps:")
            cursor.execute("SELECT step_name, status FROM chain_steps WHERE chain_id = ?", 
                          (chain_id,))
            for row in cursor.fetchall():
                print(f"- {row[0]}: {row[1]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error during analysis: {str(e)}")