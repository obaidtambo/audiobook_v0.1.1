import json
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

database='DBS/character_analysis.db'

# Pydantic model for character validation
class Character(BaseModel):
    name: str
    role: str
    description: str
    traits: List[str]

def setup_databases():
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS characters (
        id TEXT PRIMARY KEY,
        chain_id TEXT,
        book_id TEXT,
        page_number INTEGER,
        name TEXT,
        role TEXT,
        description TEXT,
        traits JSON,
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

class CharacterAnalysisPipeline:
    def __init__(self, model_name="gpt-4o-mini", temperature=0.5):
        self.llm = ChatOpenAI(model_name=model_name, temperature=temperature)
        
        # Initial extraction chain
        self.extraction_chain = (
            ChatPromptTemplate.from_messages([
                ("system", """
                Extract characters from the text below. For each character provide:
                - Name
                - Role
                - Description(Clothes/sex/body language)
                - List of personality traits
                
                Text: {text}
                
                Return a list of characters in this exact format:
                [
                    {{
                        "name": "character name",
                        "role": "character role",
                        "description": "character description",
                        "traits": ["trait1", "trait2"]
                    }}
                ]
                
                Ensure you return ONLY the JSON list, nothing else.
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
                Parse the following text into a list of characters. 
                Convert it to this exact JSON format:
                [
                    {{
                        "name": "character name",
                        "role": "character role",
                        "description": "character description",
                        "traits": ["trait1", "trait2"]
                    }}
                ]
                
                Text to parse: {text}
                
                Return ONLY the JSON list, no other text.
                """),
                ("user", "{text}")
            ])
            | self.llm
            | RunnablePassthrough()
        )
        
        setup_databases()
    
    def _log_debug(self, step: str, data: any):
        logger.debug(f"{step}:\n{json.dumps(data, indent=2)}\n{'='*50}")

    # import sqlite3
    # import uuid
    # import json
    # from datetime import datetime
    # from langchain_core.messages import AIMessage  # Ensure this import is correct


    def _save_chain_step(self, chain_id: str, step_name: str, step_data: dict, status: str):
        try:
            # Check if the input is a dict with 'output' as the key
            if "output" in step_data:
                # Extract the AIMessage object
                ai_message = step_data["output"]

                # Convert the AIMessage to a dictionary
                step_data_dict = {
                    "content": ai_message.content,
                    "additional_kwargs": ai_message.additional_kwargs,
                    "response_metadata": ai_message.response_metadata
                }
            else:
                # If 'output' key is not found, log an error message
                step_data_dict = step_data
            
            # Serialize the dictionary to a JSON-formatted string
            step_data_json = json.dumps(step_data_dict)

            # Connect to the SQLite database
            conn = sqlite3.connect(database)
            cursor = conn.cursor()

            # Generate a unique step ID
            step_id = str(uuid.uuid4())

            # Insert the data into the database
            cursor.execute(
                """INSERT INTO chain_steps (id, chain_id, step_name, step_data, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (step_id, chain_id, step_name, step_data_json, status, datetime.now())
            )

            # Commit the transaction and close the connection
            conn.commit()
            conn.close()

            # Log the operation
            self._log_debug(f"Chain Step: {step_name}", {
                "step_id": step_id,
                "chain_id": chain_id,
                "status": status,
                "data": step_data_dict
            })

        except Exception as e:
            # If an error occurs, log the exception and dump the error
            step_data_dict = {"error": str(e)}
            step_data_json = json.dumps(step_data_dict)

            # Log the error into the database (optional)
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            step_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO chain_steps (id, chain_id, step_name, step_data, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (step_id, chain_id, step_name, step_data_json, "error", datetime.now())
            )
            conn.commit()
            conn.close()

            # Log the operation with the error
            self._log_debug(f"Chain Step Error: {step_name}", {
                "step_id": step_id,
                "chain_id": chain_id,
                "status": "error",
                "data": step_data_dict
            })

        
    def _save_character(self, chain_id: str, book_id: str, page_number: int, 
                        character_data: dict, extraction_method: str, validation_status: str):
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        char_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO characters 
               (id, chain_id, book_id, page_number, name, role, description, traits, 
                extraction_method, validation_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                char_id,
                chain_id,
                book_id,
                page_number,
                character_data['name'],
                character_data['role'],
                character_data['description'],
                json.dumps(character_data['traits']),
                extraction_method,
                validation_status,
                datetime.now()
            )
        )
        
        conn.commit()
        conn.close()
        
        self._log_debug("Saved Character", {
            "character_id": char_id,
            "chain_id": chain_id,
            "data": character_data
        })

    def _validate_character(self, character_data: dict) -> bool:
        try:
            Character(**character_data)
            return True
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return False

    def _parse_json_result(self, text: str) -> List[dict]:
        """Attempt to parse the extraction result into a list of character dictionaries"""
        try:
            # Try parsing the direct output
            result = json.loads(text)
            # Handle both list and {"characters": [...]} formats
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "characters" in result:
                return result["characters"]
            else:
                raise ValueError("Unexpected JSON structure")
        except Exception as e:
            logger.error(f"Parsing error: {str(e)}")
            return None

    def analyze(self, text: str, book_id: str, page_number: int, max_retries: int = 3) -> str:
        chain_id = str(uuid.uuid4())
        logger.info(f"Starting analysis with chain_id: {chain_id}")
        
        # Step 1: Initial extraction
        extraction_result = self.extraction_chain.invoke({"text": text})
        print("#"*20)
        print(type(extraction_result))

        self._save_chain_step(chain_id, "initial_extraction", 
                              extraction_result, "completed")
        
        # Try to parse the initial extraction
        characters = self._parse_json_result(extraction_result.content)
        extraction_method = "primary"
        

        # If parsing fails, try the parser chain
        if not characters:
            logger.info("Initial parsing failed, attempting parser chain")
            extraction_method = "parser"
            for attempt in range(max_retries):
                parser_result = self.parser_chain.invoke({"text": extraction_result.content})
                self._save_chain_step(chain_id, f"parser_attempt_{attempt}", 
                                    {"output": parser_result}, "completed")
                
                characters = self._parse_json_result(parser_result.content)
                if characters:
                    break
                extraction_result = parser_result.content

        if not characters:
            error_msg = "Failed to parse character data after all attempts"
            self._save_chain_step(chain_id, "error", {"error": error_msg}, "failed")
            raise ValueError(error_msg)
        
        # Validate and save each character
        for character in characters:
            is_valid = self._validate_character(character)
            validation_status = "valid" if is_valid else "invalid"
            
            print("#"*30)
            print(character)

            self._save_character(
                chain_id=chain_id,
                book_id=book_id,
                page_number=page_number,
                character_data=character,
                extraction_method=extraction_method,
                validation_status=validation_status
            )
            
            self._save_chain_step(
                chain_id,
                "validation",
                {
                    "character": character["name"],
                    "validation_status": validation_status
                },
                "completed"
            )
        print("Success!")
        return chain_id


# Example usage
if __name__ == "__main__":
    pipeline = CharacterAnalysisPipeline()
    
    sample_text = """
    In the quiet village, Sarah the wise healer tended to the sick with her gentle touch 
    and vast knowledge of herbs. Meanwhile, John, a gruff but loyal blacksmith, worked 
    tirelessly at his forge, teaching his young apprentice Michael the secrets of metalworking.
    """
    
    try:
        chain_id = pipeline.analyze(
            text=sample_text,
            book_id="book123",
            page_number=42
        )
        
        print(f"\nAnalysis completed successfully!")
        print(f"Chain ID: {chain_id}")
        
        # Print final results
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        print("\nExtracted Characters:")
        cursor.execute("SELECT name, role, validation_status FROM characters WHERE chain_id = ?", 
                      (chain_id,))
        for row in cursor.fetchall():
            print(f"- {row[0]} ({row[1]}): {row[2]}")
        
        print("\nChain Steps:")
        cursor.execute("SELECT step_name, status FROM chain_steps WHERE chain_id = ?", 
                      (chain_id,))
        for row in cursor.fetchall():
            print(f"- {row[0]}: {row[1]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error during analysis: {str(e)}")