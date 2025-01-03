import uuid
import sqlite3
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
from char import CharacterAnalysisPipeline
from dail import DialogueAnalysisPipeline
from image import SceneGenerationPipeline
from audio import AudioGenerationPipeline

database='DBS/unified_analysis.db'

def classify_gender_from_description(description):
    # Keywords commonly associated with male, female, or neutral
    male_keywords = ['he', 'his', 'man', 'boy', 'father', 'husband', 'son']
    female_keywords = ['she', 'her', 'woman', 'girl', 'mother', 'wife', 'daughter']
    
    description_lower = description.lower()

    # Count the occurrences of male and female keywords in the description
    male_count = sum(keyword in description_lower for keyword in male_keywords)
    female_count = sum(keyword in description_lower for keyword in female_keywords)

    # Classify as 'male', 'female', or 'neutral' based on keyword frequency
    if male_count > female_count:
        return 'male'
    elif female_count > male_count:
        return 'female'
    else:
        return 'neutral'  # If neither is dominant, classify as 'neutral'


@dataclass
class VoiceMapping:
    male_voices: Dict[str, str]
    female_voices: Dict[str, str]
    neutral: Dict[str, str]

class UnifiedPipeline:
    def __init__(self):
        self.character_pipeline = CharacterAnalysisPipeline()
        self.dialogue_pipeline = DialogueAnalysisPipeline()
        self.scene_pipeline = SceneGenerationPipeline()
        self.audio_pipeline = AudioGenerationPipeline()
        
        self.conn = sqlite3.connect(database)
        self.setup_database()

    def setup_database(self):
        cursor = self.conn.cursor()
        
        # Enhanced main analysis table with processing status
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_analysis (
            analysis_id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            orientation TEXT NOT NULL,
            character_chain_id TEXT,
            dialogue_chain_id TEXT,
            scene_chain_id TEXT,
            scene_image_url TEXT,
            processing_status TEXT NOT NULL,
            failed_at_chain TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            processed_timestamp DATETIME,
            UNIQUE(book_id, page_number, text)
        )
        """)
        
        # Character-Dialogue mapping table remains the same
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS character_dialogues (
            analysis_id TEXT,
            character_name TEXT,
            character_role TEXT,
            dialogue_text TEXT,
            dialogue_tone TEXT,
            voice_id TEXT,
            audio_path TEXT,
            FOREIGN KEY (analysis_id) REFERENCES content_analysis(analysis_id)
        )
        """)
        
        self.conn.commit()

    def check_existing_analysis(self, text: str, book_id: str, page_number: int) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT analysis_id, processing_status, failed_at_chain 
            FROM content_analysis 
            WHERE book_id = ? AND page_number = ? AND text = ?
        """, (book_id, page_number, text))
        return cursor.fetchone()
    


    def analyze(self, text: str, book_id: str, page_number: int, voice_mapping: VoiceMapping, orientation: str = "landscape") -> str:
        # Check if analysis exists
        existing = self.check_existing_analysis(text, book_id, page_number)
        
        if existing:
            analysis_id, status, failed_chain = existing
            
            if status == "COMPLETED":
                print(f"Analysis already completed. Using existing analysis ID: {analysis_id}")
                return analysis_id
            elif status == "FAILED":
                print(f"Previous analysis failed at chain: {failed_chain}. Retrying...")
            elif status == "IN_PROGRESS":
                print(f"Analysis in progress. Using analysis ID: {analysis_id}")
                return analysis_id
        
        # Create new analysis or retry failed one
        analysis_id = str(uuid.uuid4()) if not existing else existing[0]
        
        try:
            cursor = self.conn.cursor()
            
            # Initialize or update analysis record
            if not existing:
                cursor.execute("""
                    INSERT INTO content_analysis 
                    (analysis_id, book_id, page_number, text, orientation, processing_status)
                    VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS')
                """, (analysis_id, book_id, page_number, text, orientation))
            else:
                cursor.execute("""
                    UPDATE content_analysis 
                    SET processing_status = 'IN_PROGRESS', failed_at_chain = NULL
                    WHERE analysis_id = ?
                """, (analysis_id,))
            
            self.conn.commit()

            # Run pipelines
            try:
                # Character Analysis
                cursor.execute("UPDATE content_analysis SET failed_at_chain = 'character' WHERE analysis_id = ?", (analysis_id,))
                character_chain_id = self.character_pipeline.analyze(text, book_id, page_number)
                
                # Dialogue Analysis
                cursor.execute("UPDATE content_analysis SET failed_at_chain = 'dialogue' WHERE analysis_id = ?", (analysis_id,))
                dialogue_chain_id = self.dialogue_pipeline.analyze(text, book_id, page_number)
                
                # Scene Analysis
                cursor.execute("UPDATE content_analysis SET failed_at_chain = 'scene' WHERE analysis_id = ?", (analysis_id,))
                scene_chain_id = self.scene_pipeline.analyze(text, book_id, page_number, orientation=orientation)
                print(scene_chain_id)
                # Get scene image URL
                scene_conn = sqlite3.connect('DBS/scene_generation.db')
                scene_cursor = scene_conn.cursor()
                scene_cursor.execute("SELECT image_url FROM generated_images WHERE scene_id = ?", (scene_chain_id,))
                image_record = scene_cursor.fetchone()
                scene_image_url = image_record[0] if image_record else None
                scene_conn.close()
                                
                # Update main record with chain IDs
                cursor.execute("""
                    UPDATE content_analysis 
                    SET character_chain_id = ?, dialogue_chain_id = ?, 
                        scene_chain_id = ?, scene_image_url = ?
                    WHERE analysis_id = ?
                """, (character_chain_id, dialogue_chain_id, scene_chain_id, scene_image_url, analysis_id))
                
                # Process characters and dialogues
                characters = self.get_characters(character_chain_id)
                dialogues = self.get_dialogues(dialogue_chain_id)

                # Add narrator character
                narrator={'name': 'Narrator',
                          'description':'Narrator of the book. Neutral',
                          'role': 'Narrator'}
                
                characters.append(narrator)
                
                cursor.execute("UPDATE content_analysis SET failed_at_chain = 'audio' WHERE analysis_id = ?", (analysis_id,))
                
                # Clear existing character dialogues if retrying
                cursor.execute("DELETE FROM character_dialogues WHERE analysis_id = ?", (analysis_id,))
                
                # Process characters and their dialogues
                for character in characters:
                    char_dialogues = [d for d in dialogues if d['speaker'] == character['name']]
                    
                    for dialogue in char_dialogues:
                        desc = character.get('description', {})
                        # def classify_gender_from_description(description):
                        #     # Keywords commonly associated with male, female, or neutral
                        #     male_keywords = ['he', 'his', 'man', 'boy', 'father', 'husband', 'son']
                        #     female_keywords = ['she', 'her', 'woman', 'girl', 'mother', 'wife', 'daughter']
                            
                        #     description_lower = description.lower()

                        #     # Count the occurrences of male and female keywords in the description
                        #     male_count = sum(keyword in description_lower for keyword in male_keywords)
                        #     female_count = sum(keyword in description_lower for keyword in female_keywords)

                        #     # Classify as 'male', 'female', or 'neutral' based on keyword frequency
                        #     if male_count > female_count:
                        #         return 'male'
                        #     elif female_count > male_count:
                        #         return 'female'
                        #     else:
                        #         return 'neutral'  # If neither is dominant, classify as 'neutral'

                            # Classify the gender based on the character's description
                        gender = classify_gender_from_description(desc)

                        # age = character.get('attributes', {}).get('age', 'default')
                        if gender == 'male':
                            voice_dict = voice_mapping.male_voices
                        elif gender == 'female':
                            voice_dict = voice_mapping.female_voices
                        else:
                            voice_dict = voice_mapping.neutral  
                        # voice_dict = voice_mapping.male_voices if gender== 'male' else voice_mapping.female_voices
                        voice_id = voice_dict['default']
                        
                        audio_path = self.audio_pipeline.generate(
                            book_id=book_id,
                            page_number=page_number,
                            character_name=character['name'],
                            dialogue_text=dialogue['content'],
                            tone=dialogue['tone'],
                            voice_id=voice_id
                        )
                        
                        cursor.execute("""
                            INSERT INTO character_dialogues 
                            (analysis_id, character_name, character_role, dialogue_text, 
                            dialogue_tone, voice_id, audio_path)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (analysis_id, character['name'], character['role'],
                             dialogue['content'], dialogue['tone'], voice_id, audio_path))
                
                # Mark as completed
                cursor.execute("""
                    UPDATE content_analysis 
                    SET processing_status = 'COMPLETED', 
                        failed_at_chain = NULL,
                        processed_timestamp = CURRENT_TIMESTAMP
                    WHERE analysis_id = ?
                """, (analysis_id,))
                
                self.conn.commit()
                print("SAVED!"*10)
                print(analysis_id)
                return analysis_id
                
            except Exception as e:
                self.conn.rollback()
                cursor.execute("""
                    UPDATE content_analysis 
                    SET processing_status = 'FAILED'
                    WHERE analysis_id = ?
                """, (analysis_id,))
                self.conn.commit()
                raise Exception(f"Pipeline failed: {str(e)}")
                
        except Exception as e:
            raise Exception(f"Error in unified pipeline: {str(e)}")

    # Previous methods remain the same
    def get_characters(self, chain_id: str) -> List[Dict]:
        conn = sqlite3.connect('DBS/character_analysis.db')
        cursor = conn.cursor()
        cursor.execute(
            """SELECT name, role, description 
            FROM characters 
            WHERE chain_id = ?""",
            (chain_id,)
        )
        characters = [
            {'name': row[0], 'role': row[1], 'description': row[2]}
            for row in cursor.fetchall()
        ]
        conn.close()
        return characters

    def get_dialogues(self, chain_id: str) -> List[Dict]:
        conn = sqlite3.connect('DBS/dialogue_analysis.db')
        cursor = conn.cursor()
        cursor.execute(
            """SELECT speaker, content, tone 
            FROM dialogues 
            WHERE chain_id = ?""",
            (chain_id,)
        )
        dialogues = [
            {'speaker': row[0], 'content': row[1], 'tone': row[2]}
            for row in cursor.fetchall()
        ]
        conn.close()
        return dialogues

    def print_combined_results(self, analysis_id: str):
        cursor = self.conn.cursor()
        
        # Get main analysis info with processing status
        cursor.execute("""
            SELECT book_id, page_number, text, scene_image_url, orientation,
                   processing_status, failed_at_chain, timestamp, processed_timestamp
            FROM content_analysis 
            WHERE analysis_id = ?
        """, (analysis_id,))
        
        analysis = cursor.fetchone()
        if not analysis:
            print("Analysis not found!")
            return
            
        print("\n=== Content Analysis Results ===")
        print(f"Analysis ID: {analysis_id}")
        print(f"Book ID: {analysis[0]}")
        print(f"Page Number: {analysis[1]}")
        print(f"Orientation: {analysis[4]}")
        print(f"Processing Status: {analysis[5]}")
        if analysis[5] == 'FAILED':
            print(f"Failed at Chain: {analysis[6]}")
        print(f"Started: {analysis[7]}")
        if analysis[8]:
            print(f"Completed: {analysis[8]}")
        
        print(f"\nOriginal Text:\n{analysis[2]}")
        print(f"\nGenerated Scene Image URL: {analysis[3]}")
        
        if analysis[5] == 'COMPLETED':
            # Get character-dialogue mappings
            cursor.execute("""
                SELECT character_name, character_role, dialogue_text, 
                       dialogue_tone, voice_id, audio_path
                FROM character_dialogues 
                WHERE analysis_id = ?
                ORDER BY character_name
            """, (analysis_id,))
            
            current_character = None
            for row in cursor.fetchall():
                char_name, char_role, dialogue, tone, voice_id, audio = row
                
                if current_character != char_name:
                    current_character = char_name
                    print(f"\n--- Character: {char_name} ---")
                    print(f"Role: {char_role}")
                
                print(f"\nDialogue: '{dialogue}'")
                print(f"Tone: {tone}")
                print(f"Voice ID: {voice_id}")
                print(f"Audio Path: {audio}")

if __name__ == "__main__":
    # Test configuration
    voice_mapping = VoiceMapping(
        male_voices={
            "default": "N2lVS1w4EtoT3dr4eOWO",
            "old": "CwhRBWXzGAHq8TQ4Fs17",
            "young": "CwhRBWXzGAHq8TQ4Fs17"
        },
        female_voices={
            "default": "XB0fDUnXU5powFXDhCwa",
            "old": "FGY2WhTYpPnrIDTdsKH5",
            "young": "FGY2WhTYpPnrIDTdsKH5"
        },
        neutral={
            "default": "cgSgspJ2msm6clMCkdW9",
            "old": "JBFqnCBsd6RMkjVDRZzb",
            "young": "JBFqnCBsd6RMkjVDRZzb"
        }
    )
    
    pipeline = UnifiedPipeline()
    
    sample_text = """
    "I can't believe what we've discovered," whispered Professor Smith, his voice trembling with excitement.
    Sarah, the young healer, looked up from the ancient tome and said, "You always say that about every new finding!"
    In the heart of the dimly lit library, dust motes danced in shafts of golden afternoon light. "whoo HOooo"
    """
    
    try:
        # First run
        print("First run of analysis:")
        analysis_id = pipeline.analyze(
            text=sample_text,
            book_id="book1234",
            page_number=42,
            voice_mapping=voice_mapping,
            orientation="portrait"
        )
        pipeline.print_combined_results(analysis_id)
        
        # Try to process same text again
        print("\nTrying to process same text again:")
        analysis_id = pipeline.analyze(
            text=sample_text,
            book_id="book1234",
            page_number=42,
            voice_mapping=voice_mapping,
            orientation="portrait"
        )
        pipeline.print_combined_results(analysis_id)
        
    except Exception as e:
        print(f"Error during unified analysis: {str(e)}")