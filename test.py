 
from ingestion import BookIngestionPipeline
pipeline = BookIngestionPipeline()
page_content = pipeline.get_book_page_content(804906, 7)
print(page_content['analysis_data'])