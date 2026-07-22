"""
WatsonX Client Module
A reusable module for interacting with IBM WatsonX Foundation Models.

Author: Babitha Padiri
"""

import os
from typing import Dict, Any, Optional, Tuple
from ibm_watson_machine_learning.foundation_models import Model


class WatsonXClientError(Exception):
    """Base exception for WatsonX client errors"""
    pass


class WatsonXAuthenticationError(WatsonXClientError):
    """Raised when authentication fails"""
    pass


class WatsonXModelError(WatsonXClientError):
    """Raised when there's an error with the model"""
    pass


class WatsonXTemplateError(WatsonXClientError):
    """Raised when there's an error with prompt templates"""
    pass


class WatsonXClient:
    """
    A reusable client for IBM WatsonX Foundation Models.

    This class provides a simple interface to interact with WatsonX models,
    including prompt loading from files and response parsing.
    """

    def __init__(
        self,
        api_key: str,
        project_id: str,
        model_id: str,
        url: str = "https://us-south.ml.cloud.ibm.com"
    ):
        """
        Initialize the WatsonX client.

        Args:
            api_key: IBM Cloud API key for WatsonX
            project_id: WatsonX project ID
            model_id: Foundation model ID to use (e.g., "mistralai/mistral-medium-2505")
            url: WatsonX service URL (default: us-south)

        Raises:
            ValueError: If any required parameter is empty or invalid
        """
        # Validate required parameters
        if not api_key or not isinstance(api_key, str):
            raise ValueError("api_key must be a non-empty string")
        if not project_id or not isinstance(project_id, str):
            raise ValueError("project_id must be a non-empty string")
        if not model_id or not isinstance(model_id, str):
            raise ValueError("model_id must be a non-empty string")
        if not url or not isinstance(url, str):
            raise ValueError("url must be a non-empty string")

        self.api_key = api_key
        self.project_id = project_id
        self.url = url
        self.model_id = model_id
        self.credentials = {
            "url": self.url,
            "apikey": self.api_key,
        }

    def load_prompt_template(self, prompt_file_path: str) -> str:
        """
        Load a prompt template from a text file.

        Args:
            prompt_file_path: Path to the prompt template file

        Returns:
            The prompt template as a string

        Raises:
            WatsonXTemplateError: If the prompt file doesn't exist or can't be read
            ValueError: If prompt_file_path is empty or invalid
        """
        if not prompt_file_path or not isinstance(prompt_file_path, str):
            raise ValueError("prompt_file_path must be a non-empty string")

        try:
            with open(prompt_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    raise WatsonXTemplateError(f"Prompt template file is empty: {prompt_file_path}")
                return content
        except FileNotFoundError:
            raise WatsonXTemplateError(f"Prompt template file not found: {prompt_file_path}")
        except PermissionError:
            raise WatsonXTemplateError(f"Permission denied reading prompt template: {prompt_file_path}")
        except Exception as e:
            raise WatsonXTemplateError(f"Error reading prompt template '{prompt_file_path}': {e}")

    def generate(
        self,
        prompt: str,
        generation_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a response from the WatsonX model.

        Args:
            prompt: The prompt to send to the model
            generation_params: Optional generation parameters
                              (e.g., {"MAX_NEW_TOKENS": 100, "MIN_NEW_TOKENS": 20})

        Returns:
            The raw response from the model

        Raises:
            ValueError: If prompt is empty or invalid
            WatsonXAuthenticationError: If authentication fails
            WatsonXModelError: If there's an error calling the model
        """
        # Validate prompt
        if not prompt or not isinstance(prompt, str):
            raise ValueError("prompt must be a non-empty string")

        # Default generation parameters
        if generation_params is None:
            generation_params = {
                "Decoding": "Greedy",
                "MIN_NEW_TOKENS": 20,
                "MAX_NEW_TOKENS": 80,
            }

        try:
            model = Model(
                self.model_id,
                self.credentials,
                generation_params,
                self.project_id
            )
            print(f"Calling WatsonX model: {self.model_id}")
            response = model.generate(prompt)

            # Validate response structure
            if not isinstance(response, dict):
                raise WatsonXModelError(f"Unexpected response type: {type(response)}")
            if "results" not in response:
                raise WatsonXModelError("Response missing 'results' field")

            return response
        except ValueError as e:
            # Re-raise validation errors
            raise
        except Exception as e:
            error_msg = str(e).lower()
            # Check for authentication errors
            if any(keyword in error_msg for keyword in ["unauthorized", "authentication", "api key", "apikey", "401"]):
                raise WatsonXAuthenticationError(f"Authentication failed: {e}")
            # Check for model-specific errors
            elif any(keyword in error_msg for keyword in ["model", "not found", "404", "invalid"]):
                raise WatsonXModelError(f"Model error: {e}")
            else:
                raise WatsonXModelError(f"Error calling WatsonX model: {e}")

    def generate_with_template(
        self,
        template_path: str,
        template_vars: Dict[str, str],
        generation_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a response using a prompt template file.

        Args:
            template_path: Path to the prompt template file
            template_vars: Dictionary of variables to substitute in the template
            generation_params: Optional generation parameters

        Returns:
            The raw response from the model

        Raises:
            ValueError: If template_vars is not a dictionary
            WatsonXTemplateError: If template loading or formatting fails
            WatsonXAuthenticationError: If authentication fails
            WatsonXModelError: If there's an error calling the model
        """
        if not isinstance(template_vars, dict):
            raise ValueError("template_vars must be a dictionary")

        try:
            template = self.load_prompt_template(template_path)
            prompt = template.format(**template_vars)
            return self.generate(prompt, generation_params)
        except KeyError as e:
            raise WatsonXTemplateError(f"Missing template variable: {e}")
        except (WatsonXTemplateError, WatsonXAuthenticationError, WatsonXModelError, ValueError):
            # Re-raise our custom exceptions and ValueError
            raise
        except Exception as e:
            raise WatsonXTemplateError(f"Error formatting template: {e}")

    @staticmethod
    def parse_multiline_response(response: Dict[str, Any], num_lines: int = 2) -> Tuple[Optional[str], ...]:
        """
        Parse a multi-line response from the model.

        Args:
            response: The raw response from the model
            num_lines: Number of lines expected in the response

        Returns:
            A tuple of parsed lines (None for missing lines)

        Raises:
            ValueError: If response is not a dictionary or num_lines is invalid
        """
        if not isinstance(response, dict):
            raise ValueError(f"response must be a dictionary, got {type(response)}")
        if not isinstance(num_lines, int) or num_lines < 1:
            raise ValueError(f"num_lines must be a positive integer, got {num_lines}")

        try:
            raw = response["results"][0]["generated_text"]
            if not isinstance(raw, str):
                print(f"Warning: generated_text is not a string: {type(raw)}")
                return tuple([None] * num_lines)

            lines = [l.strip() for l in raw.splitlines() if l.strip()]

            # Pad with None if we don't have enough lines
            while len(lines) < num_lines:
                lines.append(None)

            return tuple(lines[:num_lines])
        except (KeyError, IndexError, TypeError) as e:
            print(f"Unexpected model response format: {e!r}")
            return tuple([None] * num_lines)

    @staticmethod
    def extract_text(response: Dict[str, Any]) -> Optional[str]:
        """
        Extract the generated text from a model response.

        Args:
            response: The raw response from the model

        Returns:
            The generated text, or None if extraction fails

        Raises:
            ValueError: If response is not a dictionary
        """
        if not isinstance(response, dict):
            raise ValueError(f"response must be a dictionary, got {type(response)}")

        try:
            text = response["results"][0]["generated_text"]
            if not isinstance(text, str):
                print(f"Warning: generated_text is not a string: {type(text)}")
                return None
            return text.strip()
        except (KeyError, IndexError, TypeError) as e:
            print(f"Error extracting text from response: {e!r}")
            return None


def create_client_from_env(
    model_id: str,
    api_key_env: str = "WATSONX_API_KEY",
    project_id_env: str = "WATSONX_PROJECT_ID",
    **kwargs
) -> WatsonXClient:
    """
    Create a WatsonX client using environment variables.

    Args:
        model_id: Foundation model ID to use (required)
        api_key_env: Environment variable name for API key
        project_id_env: Environment variable name for project ID
        **kwargs: Additional arguments to pass to WatsonXClient (e.g., url)

    Returns:
        A configured WatsonXClient instance

    Raises:
        ValueError: If required environment variables are not set
    """
    api_key = os.getenv(api_key_env)
    project_id = os.getenv(project_id_env)

    if not api_key:
        raise ValueError(f"Environment variable {api_key_env} is not set")
    if not project_id:
        raise ValueError(f"Environment variable {project_id_env} is not set")

    return WatsonXClient(api_key=api_key, project_id=project_id, model_id=model_id, **kwargs)
