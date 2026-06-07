import tiktoken


def count_tokens(text: str) -> int:
    """
    Count the number of tokens in the text.

    Args:
        text (str): Input text.

    Returns:
        int: Number of tokens.
    """
    encoding = tiktoken.get_encoding("cl100k_base")  # OpenAI GPT-compatible encoding
    return len(encoding.encode(text))


def truncate_text_by_tokens(
    text: str, max_tokens: int, encoding_name: str = "cl100k_base"
) -> str:
    """
    Truncate text based on the maximum number of tokens.

    Args:
        text (str): The original text to truncate.
        max_tokens (int): Maximum number of tokens.
        encoding_name (str): The encoding name to use, defaults to "cl100k_base".

    Returns:
        str: Truncated text.
    """
    # Get encoding
    encoding = tiktoken.get_encoding(encoding_name)

    # Encode text to tokens
    tokens = encoding.encode(text)

    # Truncate if exceeds max tokens
    if len(tokens) > max_tokens:
        truncated_tokens = tokens[:max_tokens]
        truncated_text = encoding.decode(truncated_tokens)
        return truncated_text

    return text


if __name__ == "__main__":
    text = "Hello, world! This is a test text for token counting."
    print(count_tokens(text))  # Output: 11
    print(truncate_text_by_tokens(text, 5))  # Output: "Hello, world!"
