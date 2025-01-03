import json
import logging
import sqlite3
import uuid
from datetime import datetime
import os
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
from typing import Dict, Optional

database='DBS/audio_generation.db'
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class AudioGenerationPipeline:
    def __init__(self):
        # self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.api_key='sk_1d3a925149849aff129daaab29b61409cca6a330c49321c0'

        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")
        self.client = ElevenLabs(api_key=self.api_key)
        self._setup_database()

    def _setup_database(self):
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS generated_audio (
            id TEXT PRIMARY KEY,
            chain_id TEXT,
            book_id TEXT,
            page_number INTEGER,
            character_name TEXT,
            voice_id TEXT,
            dialogue_text TEXT,
            tone TEXT,
            audio_path TEXT,
            created_at TIMESTAMP
        )''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chain_steps (
            id TEXT PRIMARY KEY,
            chain_id TEXT,
            step_name TEXT,
            step_data JSON,
            status TEXT,
            created_at TIMESTAMP
        )''')
        
        conn.commit()
        conn.close()

    def _adjust_voice_settings(self, tone: str) -> VoiceSettings:
        stability = 0.75
        similarity_boost = 0.75
        
        if tone:
            tone = tone.lower()
            if 'angry' in tone or 'shouting' in tone:
                stability = 0.5
                similarity_boost = 0.8
            elif 'whisper' in tone or 'quiet' in tone:
                stability = 0.9
                similarity_boost = 0.6
            elif 'happy' in tone or 'excited' in tone:
                stability = 0.7
                similarity_boost = 0.8
            elif 'sad' in tone or 'depressed' in tone:
                stability = 0.8
                similarity_boost = 0.7
        
        return VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=0.0,
            use_speaker_boost=True
        )

    def _save_step(self, chain_id: str, step_name: str, data: dict, status: str):
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO chain_steps (id, chain_id, step_name, step_data, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), chain_id, step_name, json.dumps(data), status, datetime.now())
        )
        conn.commit()
        conn.close()

    def generate(self, book_id: str, page_number: int, character_name: str, 
                dialogue_text: str, tone: str, voice_id: str) -> str:
        chain_id = str(uuid.uuid4())
        try:
            # Setup storage
            book_folder = f"audio/{book_id}"
            os.makedirs(book_folder, exist_ok=True)
            audio_path = f"{book_folder}/{uuid.uuid4()}.mp3"
            
            # Generate audio
            voice_settings = self._adjust_voice_settings(tone)
            response = self.client.text_to_speech.convert(
                voice_id=voice_id,
                output_format="mp3_22050_32",
                text=dialogue_text,
                model_id="eleven_turbo_v2_5",
                voice_settings=voice_settings
            )
            
            # Save audio file
            with open(audio_path, "wb") as f:
                for chunk in response:
                    if chunk:
                        f.write(chunk)
            
            # Save to database
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO generated_audio 
                (id, chain_id, book_id, page_number, character_name, voice_id,
                dialogue_text, tone, audio_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), chain_id, book_id, page_number, character_name, 
                 voice_id, dialogue_text, tone, audio_path, datetime.now())
            )
            conn.commit()
            conn.close()
            
            self._save_step(chain_id, "generation", {
                "audio_path": audio_path,
                "voice_id": voice_id,
                "tone": tone
            }, "completed")
            
            return audio_path
            
        except Exception as e:
            self._save_step(chain_id, "generation", {"error": str(e)}, "failed")
            raise

if __name__ == "__main__":
    pipeline = AudioGenerationPipeline()
    audio_path = pipeline.generate(
        book_id="book123",
        page_number=42,
        character_name="Wizard",
        dialogue_text="By the ancient powers, I summon thee!",
        tone="angry",
        voice_id="cgSgspJ2msm6clMCkdW9"
    )