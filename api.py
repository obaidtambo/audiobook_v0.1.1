import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

import anthropic
import openai
from openai import OpenAI
import elevenlabs
import replicate
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ClientStatus:
    """Status of API client initialization"""
    success: bool
    error: Optional[str] = None
    client: Optional[Any] = None

class APIInitError(Exception):
    """Custom exception for API initialization errors"""
    pass

class APIConfig:
    def __init__(self, validate: bool = True):
        """
        Initialize API configuration and clients
        
        Args:
            validate (bool): Whether to validate API keys on initialization
        """
        self.status: Dict[str, ClientStatus] = {}
        
        # Load API keys
        self._load_api_keys()
        
        # Initialize base clients
        self.claude = self._init_anthropic()
        self.openai = self._init_openai()
        self.elevenlabs = self._init_elevenlabs()
        self.replicate = self._init_replicate()
        
        # Initialize LangChain models if base clients are available
        self._init_langchain_models()
        
        if validate:
            self.validate_all_clients()

    def _load_api_keys(self):
        """Load API keys from environment variables"""
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        self.eleven_labs_key = os.getenv('ELEVEN_LABS_API_KEY')
        self.openai_key = os.getenv('OPENAI_API_KEY')
        self.replicate_key = os.getenv('REPLICATE_API_KEY')
        
        # Log missing keys
        missing_keys = []
        if not self.anthropic_key: missing_keys.append('ANTHROPIC_API_KEY')
        if not self.eleven_labs_key: missing_keys.append('ELEVEN_LABS_API_KEY')
        if not self.openai_key: missing_keys.append('OPENAI_API_KEY')
        if not self.replicate_key: missing_keys.append('REPLICATE_API_KEY')
        
        if missing_keys:
            logger.warning(f"Missing API keys: {', '.join(missing_keys)}")

    def _init_anthropic(self) -> ClientStatus:
        """Initialize Anthropic client"""
        try:
            if not self.anthropic_key:
                raise APIInitError("Anthropic API key is missing")
            
            client = anthropic.Client(api_key=self.anthropic_key)
            self.status['anthropic'] = ClientStatus(True, client=client)
            logger.info("Anthropic client initialized successfully")
            return client
            
        except Exception as e:
            error_msg = f"Failed to initialize Anthropic client: {str(e)}"
            logger.error(error_msg)
            self.status['anthropic'] = ClientStatus(False, error=error_msg)
            return None

    def _init_openai(self) -> ClientStatus:
        """Initialize OpenAI client"""
        try:
            if not self.openai_key:
                raise APIInitError("OpenAI API key is missing")
            
            openai.api_key = self.openai_key
            client = OpenAI(api_key=self.openai_key)
            self.status['openai'] = ClientStatus(True, client=client)
            logger.info("OpenAI client initialized successfully")
            return client
            
        except Exception as e:
            error_msg = f"Failed to initialize OpenAI client: {str(e)}"
            logger.error(error_msg)
            self.status['openai'] = ClientStatus(False, error=error_msg)
            return None

    def _init_elevenlabs(self) -> ClientStatus:
        """Initialize ElevenLabs client"""
        try:
            if not self.eleven_labs_key:
                raise APIInitError("ElevenLabs API key is missing")
            
            elevenlabs.set_api_key(self.eleven_labs_key)
            self.status['elevenlabs'] = ClientStatus(True, client=elevenlabs)
            logger.info("ElevenLabs client initialized successfully")
            return elevenlabs
            
        except Exception as e:
            error_msg = f"Failed to initialize ElevenLabs client: {str(e)}"
            logger.error(error_msg)
            self.status['elevenlabs'] = ClientStatus(False, error=error_msg)
            return None

    def _init_replicate(self) -> ClientStatus:
        """Initialize Replicate client"""
        try:
            if not self.replicate_key:
                raise APIInitError("Replicate API key is missing")
            
            client = replicate.Client(api_key=self.replicate_key)
            self.status['replicate'] = ClientStatus(True, client=client)
            logger.info("Replicate client initialized successfully")
            return client
            
        except Exception as e:
            error_msg = f"Failed to initialize Replicate client: {str(e)}"
            logger.error(error_msg)
            self.status['replicate'] = ClientStatus(False, error=error_msg)
            return None

    def _init_langchain_models(self):
        """Initialize LangChain models"""
        # Initialize Claude
        if self.claude:
            try:
                self.langchain_claude = ChatAnthropic(
                    model_name="claude-3-sonnet-20240229",
                    anthropic_api_key=self.anthropic_key,
                    temperature=0
                )
                logger.info("LangChain Claude model initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize LangChain Claude model: {str(e)}")
                self.langchain_claude = None

        # Initialize GPT
        if self.openai:
            try:
                self.langchain_gpt = ChatOpenAI(
                    model_name="gpt-4",
                    openai_api_key=self.openai_key,
                    temperature=0
                )
                logger.info("LangChain GPT model initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize LangChain GPT model: {str(e)}")
                self.langchain_gpt = None

    def validate_all_clients(self) -> Dict[str, bool]:
        """
        Validate all initialized clients with simple API calls
        
        Returns:
            Dict[str, bool]: Status of each client
        """
        validation_results = {}
        
        # Validate Anthropic
        if self.claude:
            try:
                self.claude.messages.create(
                    model="claude-3-sonnet-20240229",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "test"}]
                )
                validation_results['anthropic'] = True
            except Exception as e:
                logger.error(f"Anthropic validation failed: {str(e)}")
                validation_results['anthropic'] = False
        
        # Validate OpenAI
        if self.openai:
            try:
                self.openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=5
                )
                validation_results['openai'] = True
            except Exception as e:
                logger.error(f"OpenAI validation failed: {str(e)}")
                validation_results['openai'] = False
        
        # Validate Replicate
        if self.replicate:
            try:
                self.replicate.version  # This will access the API
                validation_results['replicate'] = True
            except Exception as e:
                logger.error(f"Replicate validation failed: {str(e)}")
                validation_results['replicate'] = False
        
        # Validate ElevenLabs (basic key check only)
        if self.elevenlabs:
            validation_results['elevenlabs'] = True
        
        return validation_results

    def get_client_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get detailed status of all clients
        
        Returns:
            Dict[str, Dict[str, Any]]: Status information for each client
        """
        return {
            name: {
                'initialized': status.success,
                'error': status.error if not status.success else None
            }
            for name, status in self.status.items()
        }

def main():
    # Example usage
    config = APIConfig(validate=True)
    
    # Print status
    print("\nClient Status:")
    for client, status in config.get_client_status().items():
        print(f"{client}:")
        print(f"  Initialized: {status['initialized']}")
        if status['error']:
            print(f"  Error: {status['error']}")
    
    # Print validation results
    print("\nValidation Results:")
    for client, is_valid in config.validate_all_clients().items():
        print(f"{client}: {'Valid' if is_valid else 'Invalid'}")

if __name__ == "__main__":
    main()