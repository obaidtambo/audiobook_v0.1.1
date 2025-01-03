import sqlite3
import logging
from typing import Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BookDeletion:
    def __init__(self, db_path: str = 'DBS/books.db'):
        self.db_path = db_path

    def _connect_db(self) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
        """Create a database connection and return connection and cursor"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            return conn, cursor
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise

    def delete_book_records(self, book_id: str) -> tuple[bool, Optional[str]]:
        """
        Delete a book and all its associated records from the database.
        
        Args:
            book_id (str): The ID of the book to delete
            
        Returns:
            tuple[bool, Optional[str]]: (Success status, Error message if any)
        """
        try:
            conn, cursor = self._connect_db()
            
            # Start transaction
            conn.execute("BEGIN TRANSACTION")
            
            try:
                # First, verify the book exists
                cursor.execute("SELECT book_id FROM books WHERE book_id = ?", (book_id,))
                if not cursor.fetchone():
                    return False, f"Book with ID {book_id} not found"

                # Log deletion start
                logger.info(f"Starting deletion process for book_id: {book_id}")
                
                # 1. Get all analysis_ids associated with the book
                cursor.execute(
                    "SELECT analysis_id FROM page_analysis_mapping WHERE book_id = ?",
                    (book_id,)
                )
                analysis_ids = [row[0] for row in cursor.fetchall()]
                
                # # 2. Delete from dialogues table using the analysis_ids
                # if analysis_ids:
                #     cursor.execute(
                #         "DELETE FROM dialogues WHERE chain_id IN ({})".format(
                #             ','.join(['?'] * len(analysis_ids))
                #         ),
                #         analysis_ids
                #     )
                #     logger.info(f"Deleted {cursor.rowcount} records from dialogues table")
                
                # # 3. Delete from chain_steps table using the analysis_ids
                # if analysis_ids:
                #     cursor.execute(
                #         "DELETE FROM chain_steps WHERE chain_id IN ({})".format(
                #             ','.join(['?'] * len(analysis_ids))
                #         ),
                #         analysis_ids
                #     )
                #     logger.info(f"Deleted {cursor.rowcount} records from chain_steps table")
                
                # # 4. Delete from page_analysis_mapping
                # cursor.execute(
                #     "DELETE FROM page_analysis_mapping WHERE book_id = ?",
                #     (book_id,)
                # )
                # logger.info(f"Deleted {cursor.rowcount} records from page_analysis_mapping table")
                
                # 5. Finally, delete the book record
                cursor.execute(
                    "DELETE FROM books WHERE book_id = ?",
                    (book_id,)
                )
                logger.info(f"Deleted book record from books table")
                
                # Commit transaction
                conn.commit()
                logger.info(f"Successfully deleted all records for book_id: {book_id}")
                
                return True, None
                
            except sqlite3.Error as e:
                # Rollback in case of error
                conn.rollback()
                error_msg = f"Database error during deletion: {str(e)}"
                logger.error(error_msg)
                return False, error_msg
                
            finally:
                conn.close()
                
        except Exception as e:
            error_msg = f"Unexpected error during deletion: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

def main():
    # Example usage
    book_id_to_delete = "895715"
    deletion_handler = BookDeletion()
    
    success, error = deletion_handler.delete_book_records(book_id_to_delete)
    
    if success:
        print(f"Successfully deleted book {book_id_to_delete} and all associated records")
    else:
        print(f"Failed to delete book {book_id_to_delete}: {error}")

if __name__ == "__main__":
    main()