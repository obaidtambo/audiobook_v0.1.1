import os
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path
import pdfplumber
from PIL import Image
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from analysis import UnifiedPipeline, VoiceMapping
import random
import time
from tqdm import tqdm

def generate_unique_id():
    random.seed(time.time())
    return random.randint(100000, 999999)

class BookIngestionPipeline:
    def __init__(self, db_path: str = 'DBS/books.db'):
        self.db_path = db_path
        self.setup_logging()
        self.setup_database()
        
        # Initialize unified pipeline and voice mapping
        self.unified_pipeline = UnifiedPipeline()
        self.voice_mapping = VoiceMapping(
            male_voices={"default": "N2lVS1w4EtoT3dr4eOWO"},
            female_voices={"default": "XB0fDUnXU5powFXDhCwa"},
            neutral={"default": "cgSgspJ2msm6clMCkdW9"}
        )

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('book_ingestion.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_database(self):
        """Initialize the database with enhanced schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Enhanced books table with analysis tracking
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            cover_image_path TEXT,
            book_path TEXT NOT NULL,
            total_pages INTEGER,
            processed_pages INTEGER DEFAULT 0,
            analyzed_pages INTEGER DEFAULT 0,
            processing_status TEXT DEFAULT 'unprocessed',
            analysis_status TEXT DEFAULT 'unanalyzed',
            genre TEXT,
            publication_year INTEGER,
            language TEXT,
            description TEXT,
            file_hash TEXT UNIQUE,
            added_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Table to map book pages to analysis IDs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS page_analysis_mapping (
            book_id TEXT,
            page_number INTEGER,
            analysis_id TEXT,
            analysis_status TEXT,
            analysis_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (book_id, page_number),
            FOREIGN KEY (book_id) REFERENCES books(book_id)
        )
        """)

        conn.commit()
        conn.close()

    def create_book_content_table(self, book_id: str) -> None:
        """Create a table for storing the content of a specific book"""
        # Replace hyphens with underscores in book_id
        sanitized_book_id = book_id.replace('-', '_')
        table_name = f"book_content_{sanitized_book_id}"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            page_number INTEGER,
            text TEXT,
            has_images BOOLEAN,
            image_paths TEXT,
            processed BOOLEAN DEFAULT FALSE,
            analysis_id TEXT,
            analysis_status TEXT DEFAULT 'pending',
            processing_timestamp DATETIME,
            PRIMARY KEY (page_number)
        )
        """)

        conn.commit()
        conn.close()


    # ... (previous methods remain the same until process_page_content)
    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file to prevent duplicates"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def extract_pdf_metadata(self, pdf_path: str) -> Dict:
        """Extract metadata from PDF file"""
        with pdfplumber.open(pdf_path) as pdf:
            # Basic metadata
            metadata = {
                'total_pages': len(pdf.pages),
                'title': os.path.splitext(os.path.basename(pdf_path))[0],  # Default to filename
                'author': 'Unknown',
                'publication_year': None,
                'language': 'en',  # Default to English
                'genre': 'Unspecified'
            }

            # Try to get PDF document info if available
            if pdf.metadata:
                metadata['title'] = pdf.metadata.get('Title', metadata['title'])
                metadata['author'] = pdf.metadata.get('Author', 'Unknown')
                
                # Try to extract year from PDF metadata
                if 'CreationDate' in pdf.metadata:
                    creation_date = pdf.metadata['CreationDate']
                    if creation_date.startswith('D:') and len(creation_date) >= 8:
                        metadata['publication_year'] = int(creation_date[2:6])

            return metadata



    def save_first_page_as_cover(self, pdf_path: str, book_id: str) -> Optional[str]:
        """Extract first page as cover image"""
        try:
            # Ensure the directory for storing covers exists
            covers_dir = Path('book_covers')
            covers_dir.mkdir(exist_ok=True)
            
            # Define the path where the cover image will be saved
            cover_path = covers_dir / f"{book_id}_cover.jpg"
            
            # Open the PDF and extract the first page
            with pdfplumber.open(pdf_path) as pdf:
                first_page = pdf.pages[0]
                page_image = first_page.to_image()  # Convert the first page to an image
                
                # Access the underlying PIL Image instance
                pil_image = page_image.annotated
                
                # If the image is in 'P' mode (palette-based), convert it to 'RGB' mode
                if pil_image.mode == 'P':
                    pil_image = pil_image.convert('RGB')  # Convert to RGB mode before saving
                
                # Save the image as a JPEG
                pil_image.save(str(cover_path), format='JPEG')
            
            # Return the path of the saved cover image
            return str(cover_path)
        
        except Exception as e:
            self.logger.error(f"Failed to extract cover image: {e}")
            return None


    def process_page_content(self, page) -> Tuple[str, List[str]]:
        """Process a single page and extract text and images"""
        text = page.extract_text() or ""
        image_paths = []
        
        # Extract images if present
        try:
            images = page.images
            if images:
                images_dir = Path('book_images')
                images_dir.mkdir(exist_ok=True)
                
                for idx, img in enumerate(images):
                    img_path = images_dir / f"{page.page_number}_{idx}.jpg"
                    # Convert image data to file
                    # Note: This is a simplified version - you might need more complex
                    # image processing depending on your needs
                    image_paths.append(str(img_path))
        except Exception as e:
            self.logger.warning(f"Failed to extract images from page {page.page_number}: {e}")
        
        return text, image_paths

    def process_page_for_analysis(self, book_id: str, page_number: int, text: str, conn) -> str:
        """Process a single page through the unified pipeline"""
        try:
            # Run unified pipeline analysis
            analysis_id = self.unified_pipeline.analyze(
                text=text,
                book_id=book_id,
                page_number=page_number,
                voice_mapping=self.voice_mapping,
                orientation="portrait"  # You might want to make this configurable
            )

            cursor = conn.cursor()
            # Update page analysis mapping
            cursor.execute("""
                INSERT INTO page_analysis_mapping 
                (book_id, page_number, analysis_id, analysis_status)
                VALUES (?, ?, ?, 'completed')
            """, (book_id, page_number, analysis_id))

            # Update book content table
            cursor.execute(f"""
                UPDATE book_content_{book_id}
                SET analysis_id = ?,
                    analysis_status = 'completed'
                WHERE page_number = ?
            """, (analysis_id, page_number))

            conn.commit()
            return analysis_id

        except Exception as e:
            self.logger.error(f"Analysis failed for page {page_number}: {e}")
            # Update status to failed
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE book_content_{book_id}
                SET analysis_status = 'failed'
                WHERE page_number = ?
            """, (page_number,))
            conn.commit()
            return None

    def ingest_book(self, pdf_path: str, metadata_override: Optional[Dict] = None) -> str:
        """Enhanced ingest_book method with unified pipeline integration"""
        try:
            book_id = str(generate_unique_id())
            file_hash = self.calculate_file_hash(pdf_path)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check for existing book
            cursor.execute("SELECT book_id FROM books WHERE file_hash = ?", (file_hash,))
            existing_book = cursor.fetchone()
            if existing_book:
                return existing_book[0]
            
            metadata = self.extract_pdf_metadata(pdf_path)
            if metadata_override:
                metadata.update(metadata_override)
            
            cover_path = self.save_first_page_as_cover(pdf_path, book_id)
            self.create_book_content_table(book_id)
            
            # Insert initial book record
            cursor.execute("""
                INSERT INTO books (
                    book_id, title, author, cover_image_path, book_path,
                    total_pages, genre, publication_year, language,
                    file_hash, processing_status, analysis_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing', 'analyzing')
            """, (
                book_id, metadata['title'], metadata['author'], cover_path,
                pdf_path, metadata['total_pages'], metadata['genre'],
                metadata['publication_year'], metadata['language'],
                file_hash
            ))
            print("##"*20)
            analyzed_pages = 0
            with pdfplumber.open(pdf_path) as pdf:
                # for page_num, page in enumerate(pdf.pages, 1):
                total_pages = len(pdf.pages)
                for page_num, page in tqdm(enumerate(pdf.pages, 1), total=total_pages, desc="Processing Pages"):        
                    text, image_paths = self.process_page_content(page)
                    print("Here 2")
                    # Store page content
                    cursor.execute(f"""
                        INSERT INTO book_content_{book_id} (
                            page_number, text, has_images, image_paths,
                            processed, processing_timestamp
                        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        page_num, text, bool(image_paths),
                        ','.join(image_paths) if image_paths else None,
                        True
                    ))
                    
                    # Process through unified pipeline
                    analysis_id = self.process_page_for_analysis(book_id, page_num, text, conn)
                    if analysis_id:
                        analyzed_pages += 1
                    print("Here 3")
                    print(analysis_id)
                    # Update progress
                    cursor.execute("""
                        UPDATE books 
                        SET processed_pages = ?,
                            analyzed_pages = ?
                        WHERE book_id = ?
                    """, (page_num, analyzed_pages, book_id))
                    
                    conn.commit()
                    
                    if page_num % 5 == 0:
                        self.logger.info(f"Processed and analyzed {page_num} pages of {metadata['title']}")
            
            # Update final status
            final_analysis_status = 'analyzed' if analyzed_pages == metadata['total_pages'] else 'partially_analyzed'
            cursor.execute("""
                UPDATE books 
                SET processing_status = 'processed',
                    analysis_status = ?,
                    processed_pages = total_pages,
                    analyzed_pages = ?
                WHERE book_id = ?
            """, (final_analysis_status, analyzed_pages, book_id))
            
            conn.commit()
            self.logger.info(f"Successfully ingested and analyzed book: {metadata['title']} (ID: {book_id})")
            
            return book_id
            
        except Exception as e:
            self.logger.error(f"Failed to ingest book: {e}")
            if 'conn' in locals():
                conn.rollback()
            raise
        finally:
            if 'conn' in locals():
                conn.close()

    def get_book_page_content(self, book_id: str, page_number: int) -> Optional[Dict]:
        """Enhanced page content retrieval with analysis information"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get page content and analysis ID
            cursor.execute(f"""
                SELECT bc.text, bc.has_images, bc.image_paths, bc.analysis_id,
                       pam.analysis_status
                FROM book_content_{book_id} bc
                LEFT JOIN page_analysis_mapping pam 
                    ON bc.page_number = pam.page_number 
                    AND pam.book_id = ?
                WHERE bc.page_number = ?
            """, (book_id, page_number))
            
            result = cursor.fetchone()
            if result:
                text, has_images, image_paths, analysis_id, analysis_status = result
                
                # Get analysis details if available
                analysis_data = None
                if analysis_id and analysis_status == 'completed':
                    analysis_conn = sqlite3.connect('DBS/unified_analysis.db')
                    analysis_cursor = analysis_conn.cursor()
                    
                    # Get scene image and dialogues
                    analysis_cursor.execute("""
                        SELECT scene_image_url FROM content_analysis 
                        WHERE analysis_id = ?
                    """, (analysis_id,))
                    scene_data = analysis_cursor.fetchone()
                    
                    analysis_cursor.execute("""
                        SELECT character_name, dialogue_text, audio_path 
                        FROM character_dialogues 
                        WHERE analysis_id = ?
                    """, (analysis_id,))
                    dialogues = analysis_cursor.fetchall()
                    
                    analysis_data = {
                        'scene_image_url': scene_data[0] if scene_data else None,
                        'dialogues': [
                            {
                                'character': d[0],
                                'text': d[1],
                                'audio_path': d[2]
                            } for d in dialogues
                        ]
                    }
                    analysis_conn.close()
                
                return {
                    'text': text,
                    'has_images': has_images,
                    'image_paths': image_paths.split(',') if image_paths else [],
                    'analysis_id': analysis_id,
                    'analysis_status': analysis_status,
                    'analysis_data': analysis_data
                }
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to retrieve page content: {e}")
            return None
        finally:
            if 'conn' in locals():
                conn.close()

# Example usage
if __name__ == "__main__":
    pipeline = BookIngestionPipeline()
    
    try:
        book_id = pipeline.ingest_book(
            pdf_path='PDF\07. The Yellow Wall-Papper, Charlotte Perkins Stetson.pdf',
            metadata_override={
                'author': 'Obaid Tamboli',
                'genre': 'Science Fiction',
                'language': 'en',
                'publication_year': 2024
            }
        )
        print(f"Successfully processed book with ID: {book_id}")
        
        # Get content with analysis
        page_content = pipeline.get_book_page_content(book_id, 1)
        if page_content:
            print("Page 1 content:", page_content['text'][:200])
            if page_content['analysis_data']:
                print("Analysis available with scene image and dialogues")
    except Exception as e:
        print(f"Failed to process book: {e}")