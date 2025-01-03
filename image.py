import json
import logging
import sqlite3
import uuid
from datetime import datetime
from PIL import Image
import io
import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from langchain_community.llms import Replicate
# from langchain.chains import LLMChain
# from langchain_community.llms import Replicate
from langchain_core.prompts import PromptTemplate
import replicate

database='DBS/scene_generation.db'
# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def setup_databases():
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS scene_descriptions (
        id TEXT PRIMARY KEY,
        chain_id TEXT,
        book_id TEXT,
        page_number INTEGER,
        source_text TEXT,
        scene_description TEXT,
        orientation TEXT,
        created_at TIMESTAMP
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS generated_images (
        id TEXT PRIMARY KEY,
        chain_id TEXT,
        scene_id TEXT,
        image_url TEXT,
        generation_params TEXT,
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

class SceneGenerationPipeline:
    def __init__(self, model_name="gpt-4o-mini", temperature=0.7):
        self.llm = ChatOpenAI(model_name=model_name, temperature=temperature)
        
        # Scene description generation chain with improved prompt
        self.description_chain = (
            ChatPromptTemplate.from_messages([
                ("system", """
                Create a comprehensive scene description for image generation. Format your response 
                as a single, detailed paragraph that includes all the following elements in a natural, 
                flowing way:

                Essential Elements to Include:
                1. Camera Angle/View: Start by specifying the shot composition (e.g., "Viewed from a low angle," 
                   or "From an intimate eye-level perspective")
                
                2. Core Scene Elements:
                   - Main subject positioning and focus
                   - Setting details and environment
                   - Time of day and lighting conditions
                   - Weather and atmospheric effects (if applicable)
                   
                3. Character Details (if present):
                   - Physical appearance and clothing
                   - Poses and expressions
                   - Interactions with environment
                   
                4. Lighting and Mood:
                   - Light sources and shadows
                   - Color palette
                   - Emotional atmosphere
                   
                5. Technical Considerations:
                   - Depth and perspective
                   - Key foreground and background elements
                   - Important textures and materials
                   - Composition optimized for {orientation} format

                Based on the above description write a cinematographer's scene setup that can be explained in less than 50 words to a child. The setting the number of charactes and the lightning Write everything as one flowing, natural phraase that reads like a 
                cinematographer's scene setup. Start with the camera angle/perspective. Make sure the phrase does justice to the scene and is not more than 50 words.

                Text to analyze: {text}
                """),
#                 ('system',  """You are a style and universe analyzer. Identify and refine scene descriptions to match one of these styles:

# Harry Potter: Magical, whimsical settings with enchanted details.
# Lord of the Rings: Majestic landscapes with timeless beauty.
# Studio Ghibli’s Spirited Away: Soft, surreal atmospheres blending natural and fantastical elements.
# Dungeons & Dragons: Lively fantasy settings with vibrant characters and interactions.
# The Witcher: Dark, gritty worlds with realistic, eerie magical elements.
# Elden Ring: Hauntingly beautiful, mysterious ruins and expansive landscapes.
# For a given text:

# Analyze the setting, mood, and characters (including actions, appearance, and expressions).
# Match it to the closest style.
# Refine the description to align with the style and characters, limited to 50 tokens.
# Output format:

# Style/Universe: [Detected style]
# Refined Description: [Enhanced description within 50 tokens]
# Ensure accuracy and brevity in all enhancements. Text to Anlyze: """ ),

                ("user", "{text}")
            ])
            | self.llm
            | RunnablePassthrough()
        )
        
        # Initialize Replicate model
        self.model_id = "bytedance/sdxl-lightning-4step:5599ed30703defd1d160a25a63321b4dec97101d98b4674bcc56e41f62f35637"
        # self.image_generator = Replicate()
        setup_databases()
    
    def _log_debug(self, step: str, data: any):
        logger.debug(f"{step}:\n{json.dumps(data, indent=2)}\n{'='*50}")

    def _save_chain_step(self, chain_id: str, step_name: str, step_data: dict, status: str):
        try:
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            
            step_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO chain_steps (id, chain_id, step_name, step_data, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (step_id, chain_id, step_name, json.dumps(step_data), status, datetime.now())
            )
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving chain step: {str(e)}")

    def _save_scene_description(self, chain_id: str, book_id: str, page_number: int,
                              source_text: str, scene_description: str, orientation: str) -> str:
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        scene_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO scene_descriptions 
               (id, chain_id, book_id, page_number, source_text, scene_description,
                orientation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scene_id,
                chain_id,
                book_id,
                page_number,
                source_text,
                scene_description,
                orientation,
                datetime.now()
            )
        )
        
        conn.commit()
        conn.close()
        return scene_id

    def _save_generated_image(self, chain_id: str, scene_id: str, 
                            image_url: str, generation_params: dict):
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        image_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO generated_images 
               (id, chain_id, scene_id, image_url, generation_params, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                image_id,
                chain_id,
                scene_id,
                image_url,
                json.dumps(generation_params),
                datetime.now()
            )
        )
        
        conn.commit()
        conn.close()

    def _prepare_image_params(self, scene_description: str, orientation: str) -> dict:
        """Prepare parameters for image generation matching the example"""
        return {
                "width": 1024 if orientation== 'landscape' else 512,
                "height": 712 if orientation== 'landscape' else 712,
                "prompt": "Medivial Period with"+ str(scene_description),
                "disable_safety_checker": True,
                "scheduler": "K_EULER",
                "num_outputs": 1,
                "guidance_scale": 0.6,
                "negative_prompt": "worst quality, low quality, ",
                "num_inference_steps": 4     
        }






    def _save_and_render_image(self, image_data, book_id: str, scene_id: str):
        """Save the image file and render it in terminal"""
        # Create folder structure if it doesn't exist
        book_folder = f"images/{book_id}"
        os.makedirs(book_folder, exist_ok=True)
        
        # Create filename using scene_id
        image_path = f"{book_folder}/{scene_id}.png"
        
        # Convert the image data to bytes if it isn't already
        if hasattr(image_data, 'read'):
            image_bytes = image_data.read()
        else:
            image_bytes = image_data
        
        # Save the image
        with open(image_path, 'wb') as f:
            f.write(image_bytes)
        
        # Render in terminal
        try:
            # Create a copy of the image data for PIL
            image_data_copy = io.BytesIO(image_bytes)
            image = Image.open(image_data_copy)
            
            # Resize for terminal display (adjust these numbers based on your terminal size)
            terminal_width = 80  # default terminal width
            terminal_height = 24  # default terminal height
            
            # Calculate aspect ratio
            aspect = image.width / image.height
            new_width = min(terminal_width, int(terminal_height * aspect * 2))  # multiply by 2 because characters are taller than wide
            new_height = int(new_width / aspect / 2)
            
            # Resize image
            image = image.resize((new_width, new_height))
            
            # Convert to ASCII
            pixels = image.convert('L').getdata()
            
            # ASCII characters from dark to light
            ascii_chars = '@%#*+=-:. '
            
            # Print the image
            print("\nGenerated Image Preview:")
            print("-" * (new_width + 2))
            for i in range(new_height):
                line = ''
                for j in range(new_width):
                    pixel_value = pixels[i * new_width + j]
                    char_index = (pixel_value * (len(ascii_chars) - 1)) // 255
                    line += ascii_chars[char_index]
                print(f"|{line}|")
            print("-" * (new_width + 2))
            print(f"Full image saved at: {image_path}\n")
            
        except Exception as e:
            logger.warning(f"Could not render image in terminal: {str(e)}")
            print(f"Image saved at: {image_path}")
        
        return image_path


    def analyze(self, text: str, book_id: str, page_number: int, 
               orientation: str = "landscape") -> str:
        chain_id = str(uuid.uuid4())
        logger.info(f"Starting scene generation with chain_id: {chain_id}")
        
        try:
            # Generate scene description
            description_result = self.description_chain.invoke({
                "text": text,
                "orientation": orientation
            })
            
            scene_description = description_result.content.strip()
            print(scene_description)
            self._save_chain_step(
                chain_id, 
                "description_generation", 
                {"description": scene_description}, 
                "completed"
            )
            
            # Save scene description
            scene_id = self._save_scene_description(
                chain_id=chain_id,
                book_id=book_id,
                page_number=page_number,
                source_text=text,
                scene_description=scene_description,
                orientation=orientation
            )
            
            # Generate image with corrected parameters
            try:
                params = self._prepare_image_params(scene_description, orientation)
                # image_url = self.image_generator(**params)
                output=replicate.run("bytedance/sdxl-lightning-4step:5599ed30703defd1d160a25a63321b4dec97101d98b4674bcc56e41f62f35637",input=params)
                            # Save image file locally and render in terminal
                # output = replicate.run(
                #         "recraft-ai/recraft-v3",
                #         input={
                #             "size": "1024x1536",
                #             "style": "digital_illustration",
                #             "prompt": scene_description
                #         }
                #     )            
                image_path = self._save_and_render_image(output[0], book_id, scene_id)
                print('***'*50)
                print(image_path)
                print(" "*50)
                self._save_generated_image(
                    chain_id=chain_id,
                    scene_id=scene_id,
                    image_url=image_path,
                    generation_params=params
                )
                
                self._save_chain_step(
                    chain_id, 
                    "image_generation", 
                    {"image_url": image_path}, 
                    "completed"
                )
                
            except Exception as e:
                logger.error(f"Image generation failed: {str(e)}")
                self._save_chain_step(
                    chain_id, 
                    "image_generation", 
                    {"error": str(e)}, 
                    "failed"
                )
                raise
            
        except Exception as e:
            logger.error(f"Pipeline error: {str(e)}")
            self._save_chain_step(
                chain_id, 
                "pipeline_error", 
                {"error": str(e)}, 
                "failed"
            )
            raise
        
        return scene_id

# Example usage
if __name__ == "__main__":
    pipeline = SceneGenerationPipeline()
    
    # Test text
    sample_text = """
    In the heart of an ancient library, dust motes dance in shafts of golden 
    afternoon light. A young scholar in worn robes stands before a towering 
    bookshelf, carefully holding a mysterious glowing manuscript. The air is 
    thick with the scent of old parchment and magical possibility.
    """
    
    try:
        # Test with landscape orientation
        chain_id = pipeline.analyze(
            text=sample_text,
            book_id="book123",
            page_number=42,
            orientation="potrait"
        )
        
        # Print results
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        
        # Print scene description
        cursor.execute("""
            SELECT scene_description, orientation 
            FROM scene_descriptions 
            WHERE chain_id = ?
        """, (chain_id,))
        
        scene_data = cursor.fetchone()
        if scene_data:
            print("\nGenerated Scene Description:")
            print(scene_data[0])
            print(f"\nOrientation: {scene_data[1]}")
        
        # Print image details
        cursor.execute("""
            SELECT image_url, generation_params 
            FROM generated_images 
            WHERE chain_id = ?
        """, (chain_id,))
        
        image_data = cursor.fetchone()
        if image_data:
            print(f"\nGenerated Image URL: {image_data[0]}")
        
        # Print chain steps
        print("\nChain Steps:")
        cursor.execute("""
            SELECT step_name, status 
            FROM chain_steps 
            WHERE chain_id = ?
        """, (chain_id,))
        
        for row in cursor.fetchall():
            print(f"- {row[0]}: {row[1]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error during generation: {str(e)}")