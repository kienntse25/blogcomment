# run_content_generation.py
import logging
from src.generative_ai import generate_content_from_excel

if __name__ == "__main__":
    # Cấu hình logging để xem tiến trình
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    generate_content_from_excel()
