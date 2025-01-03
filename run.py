import streamlit as st
import sqlite3
from pathlib import Path
import pandas as pd
from datetime import datetime
import base64
from typing import Optional, Dict, List
import json

# Set page configuration for a wider layout
st.set_page_config(layout="wide", page_title="Immersive Book Reader", page_icon="🎧")

# Set page configuration
# st.set_page_config(layout="wide", page_title="Immersive Book Reader", page_icon="🎧")

# Enhanced futuristic CSS
st.markdown("""
<style>
    /* Main app styling */
    .stApp {
        background: linear-gradient(180deg, #0a0a1f 0%, #1a1a3a 100%);
        color: #e0e0ff;
    }
    
    /* Profile section */
    .profile-section {
        background: rgba(30, 30, 60, 0.4);
        border-radius: 15px;
        padding: 20px;
        margin: 10px 0;
        backdrop-filter: blur(8px);
        border: 1px solid rgba(123, 104, 238, 0.2);
    }
    
    .profile-image {
        width: 80px;
        height: 80px;
        border-radius: 50%;
        margin: 10px auto;
        display: block;
        border: 2px solid #9951ff;
    }
    
    /* Enhanced book card */
    .book-card {
        background: rgba(40, 40, 80, 0.4);
        border-radius: 20px;
        padding: 25px;
        margin: 15px;
        backdrop-filter: blur(12px);
        border: 1px solid rgba(123, 104, 238, 0.3);
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    
    .book-card:hover {
        transform: translateY(-8px);
        box-shadow: 0 8px 25px rgba(153, 81, 255, 0.3);
    }
    
    /* Reader container with reflections */
    .reader-container {
        position: relative;
        background: rgba(30, 30, 60, 0.95);
        border-radius: 20px;
        padding: 30px;
        margin: 40px 0;
        backdrop-filter: blur(15px);
    }
    
    .reader-container::before,
    .reader-container::after {
        content: '';
        position: absolute;
        left: 0;
        width: 100%;
        height: 40%;
        background: inherit;
        border-radius: 20px;
        opacity: 0.3;
        transform: perspective(100px) rotateX(2deg);
        filter: blur(10px);
    }
    
    .reader-container::before {
        top: -30px;
        transform: perspective(100px) rotateX(-2deg);
    }
    
    .reader-container::after {
        bottom: -30px;
    }
    
    /* Audio dialogue styling */
    .dialogue-text {
        background: linear-gradient(90deg, rgba(153, 81, 255, 0.1) 0%, rgba(153, 81, 255, 0.2) 100%);
        border-radius: 8px;
        padding: 8px 15px;
        margin: 8px 0;
        cursor: pointer;
        border-left: 3px solid #9951ff;
        transition: all 0.2s ease;
    }
    
    .dialogue-text:hover {
        background: rgba(153, 81, 255, 0.3);
        transform: translateX(5px);
    }
    
    /* Audio player container */
    .audio-container {
        background: rgba(20, 20, 45, 0.6);
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
        backdrop-filter: blur(8px);
        border: 1px solid rgba(123, 104, 238, 0.2);
    }
    
    /* Image reflection effect */
    .scene-image-container {
        position: relative;
        margin: 40px 0;
    }
    
    .scene-image {
        border-radius: 15px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
    }
    
    .scene-image-reflection {
        position: absolute;
        width: 100%;
        height: 60%;
        bottom: -60%;
        transform: scaleY(-1);
        opacity: 0.4;
        background: linear-gradient(to bottom, rgba(30, 30, 60, 0.8), transparent);
        border-radius: 15px;
        filter: blur(3px);
    }
    
    /* Navigation controls */
    .control-panel {
        background: rgba(20, 20, 45, 0.8);
        border-radius: 15px;
        padding: 20px;
        margin-top: 20px;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(123, 104, 238, 0.2);
    }
</style>
""", unsafe_allow_html=True)


class BookDatabase:
    def __init__(self, db_path: str = 'DBS/books.db'):
        self.db_path = db_path
        
    def get_all_books(self) -> pd.DataFrame:
        """Fetch all books from the database"""
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            book_id, title, author, cover_image_path, total_pages,
            genre, publication_year, language, description, added_date
        FROM books
        ORDER BY added_date DESC
        """
        books_df = pd.read_sql_query(query, conn)
        conn.close()
        return books_df
    
    def get_book_content(self, book_id: str, page_number: int) -> Dict:
        """Get content for a specific page of a book"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get page content
        cursor.execute(f"""
            SELECT text, has_images, image_paths, analysis_id
            FROM book_content_{book_id}
            WHERE page_number = ?
        """, (page_number,))
        
        content = cursor.fetchone()
        if not content:
            return None
            
        # Get analysis data
        analysis_conn = sqlite3.connect('DBS/unified_analysis.db')
        analysis_cursor = analysis_conn.cursor()
        
        analysis_data = {
            'scene_image': None,
            'dialogues': []
        }
        
        if content[3]:  # If analysis_id exists
            # Get scene image
            analysis_cursor.execute("""
                SELECT scene_image_url 
                FROM content_analysis 
                WHERE analysis_id = ?
            """, (content[3],))
            scene_data = analysis_cursor.fetchone()
            if scene_data:
                analysis_data['scene_image'] = scene_data[0]
            
            # Get dialogues
            analysis_cursor.execute("""
                SELECT character_name, dialogue_text, audio_path 
                FROM character_dialogues 
                WHERE analysis_id = ?
            """, (content[3],))
            dialogues = analysis_cursor.fetchall()
            analysis_data['dialogues'] = [
                {
                    'character': d[0],
                    'text': d[1],
                    'audio_path': d[2]
                } for d in dialogues
            ]
        
        return {
            'text': content[0],
            'images': content[2].split(',') if content[2] else [],
            'analysis': analysis_data
        }
    


import streamlit as st
from typing import Dict

def show_reader(book_id: str):
    """Reader view with three-column layout"""
    db = BookDatabase()  # Assuming your database class is defined elsewhere
    book_info = db.get_all_books()[db.get_all_books().book_id == book_id].iloc[0]
    
    # Sidebar controls
    with st.sidebar:
        st.title(book_info.title)
        st.write(f"By {book_info.author}")
        font_size = st.slider("Font Size", 12, 24, 16)
        font_family = st.selectbox("Font Family", 
                                 ["Georgia", "Arial", "Verdana"])
        current_page = st.number_input("Page", 1, book_info.total_pages, 1)
    
    # Main content
    content = db.get_book_content(book_id, current_page)
    if content:
        # Create three columns with audio icons, text, and image
        audio_col, text_col, image_col = st.columns([1, 5, 3])
        
        # Audio column (left)
        with audio_col:
            st.markdown("### 🎧")
            # Create audio controls and store references
            audio_elements = {}
            for idx, dialogue in enumerate(content['analysis']['dialogues']):
                # Store audio element
                audio_elements[dialogue['audio_path']] = st.audio(
                    dialogue['audio_path'],
                    format='audio/mp3'
                )
        
        # Text column (middle)
        with text_col:
            # Apply the custom CSS for the scrollable text area
            st.markdown("""
            <style>
                .scrollable-text {
                    max-height: 700px;
                    overflow-y: auto;
                    padding: 10px;
                    border: 1px solid #ddd;
                    border-radius: 5px;

                }
            </style>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="scrollable-text" style="font-family: {font_family}; font-size: {font_size}px;">
                {process_text_for_display(content)}
            </div>
            """, unsafe_allow_html=True)
        
        # Image column (right)
        with image_col:
            st.write("")
            st.write("")
            st.write("")

            if content['analysis']['scene_image']:
                st.image(
                    content['analysis']['scene_image'],
                    caption="AI Generated Scene",
                    use_container_width=True
                )

def process_text_for_display(content: Dict) -> str:
    """Process text with highlighted dialogues"""
    text = content['text']
    for idx, dialogue in enumerate(content['analysis']['dialogues']):
        # Create clickable sections that trigger audio via session state
        highlighted_text = f"""
        <div class="dialogue-text" onclick="document.querySelector('button[key=\\"audio_btn_{idx}\\"]').click()">
            {dialogue['text']}
        </div>
        """
        text = text.replace(dialogue['text'], highlighted_text)
    return text



import streamlit as st
import sqlite3
from pathlib import Path
import pandas as pd
from datetime import datetime
import base64
from typing import Optional, Dict, List
import json


def show_library():
    """Enhanced library view with profile section"""
    # Sidebar with profile
    with st.sidebar:
        st.image("https://api.dicebear.com/7.x/avataaars/svg?seed=Felix", width=100)
        st.title("Welcome, Reader")
        st.write("Premium Member")
        
        # Profile stats
        st.markdown("""
        <div class="profile-section">
            <h3>Reading Stats</h3>
            <p>Books Read: 42</p>
            <p>Reading Streak: 15 days</p>
            <p>Average Daily: 45 mins</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Main content
    st.title("📚 Your Digital Library")
    
    # Featured section
    st.subheader("Continue Reading")
    progress_col1, progress_col2 = st.columns(2)
    with progress_col1:
        st.progress(0.7, "The Great Gatsby - 70%")
    with progress_col2:
        st.progress(0.3, "1984 - 30%")
    
    # Library grid
    st.subheader("Your Collection")
    db = BookDatabase()
    books = db.get_all_books()
    
    cols = st.columns(4)
    for idx, book in books.iterrows():
        with cols[idx % 4]:
            st.markdown(f"""
            <div class="book-card">
                <img src="{book.cover_image_path}" style="width:100%; border-radius:12px;">
                <h3 style="margin-top:15px;">{book.title}</h3>
                <p style="color:#b794f4;">{book.author}</p>
                <div style="display:flex; justify-content:space-between; margin-top:10px;">
                    <span>{book.genre}</span>
                    <span>{book.publication_year}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            cols_new = st.columns([1,5,1])
            with cols_new[1]:
                if st.button(f"Read Now ###{book.book_id}", key=f"read_{book.book_id}"):
                    st.session_state.current_book = book.book_id
                    st.session_state.page = "reader"
                    st.rerun()

# Main app logic
if 'page' not in st.session_state:
    st.session_state.page = "library"
    
if st.session_state.page == "library":
    show_library()
elif st.session_state.page == "reader":
    show_reader(st.session_state.current_book)



# Improvements - One Create a RAG for Us to Just get the major characters.
# Ask the Question to get the Setting... in ten Words. Maybe if possible chapter wise?
#
