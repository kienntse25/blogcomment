from __future__ import annotations
import os
import time
import pandas as pd
import google.generativeai as genai
from logging import getLogger
from dotenv import load_dotenv

log = getLogger(__name__)


def configure_gemini_api():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.error("Biến môi trường GEMINI_API_KEY chưa được thiết lập. Không thể sử dụng Gemini.")
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        log.error(f"Lỗi khi cấu hình Gemini API: {e}")
        return False


def generate_content_from_excel(
    file_path: str = "data/comments.xlsx",
    keyword_col: str = "keywords",
    content_col: str = "comment",
):
    """
    Đọc file Excel, dùng cột keywords để tạo nội dung bằng Gemini và cập nhật lại cột content.
    """
    if not os.path.exists(file_path):
        log.error(f"File không tồn tại: {file_path}")
        return

    if not configure_gemini_api():
        return

    log.info(f"Đang đọc file Excel: {file_path}")
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except Exception as e:
        log.error(f"Không thể đọc file Excel: {e}")
        return

    if keyword_col not in df.columns:
        log.error(f"Không tìm thấy cột '{keyword_col}' trong file Excel.")
        return

    # 1. Thu thập các keywords và chỉ số dòng tương ứng
    tasks = []
    for index, row in df.iterrows():
        keyword_val = row.get(keyword_col)
        # Bỏ qua các giá trị rỗng hoặc NaN (Not a Number) từ Excel
        if keyword_val and not pd.isna(keyword_val):
            keyword = str(keyword_val).strip()
            tasks.append({"index": index, "keyword": keyword})

    if not tasks:
        log.warning("Không có keyword nào hợp lệ để tạo nội dung.")
        return

    log.info(f"Tìm thấy {len(tasks)} keywords. Bắt đầu tạo nội dung bằng Gemini Flash...")

    # 2. Gọi Gemini API để tạo nội dung cho từng keyword
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    results_to_update = []
    request_count = 0

    for task in tasks:
        # Giới hạn tốc độ: nghỉ 1 phút sau mỗi 15 request
        if request_count > 0 and request_count % 15 == 0:
            log.info("Đã đạt giới hạn 15 requests. Tạm nghỉ 60 giây...")
            time.sleep(60)
            log.info("Tiếp tục tạo nội dung...")

        keyword = task["keyword"]
        prompt = f"Viết content giới thiệu về {keyword}, độ dài 50 từ"
        try:
            response = model.generate_content(prompt)
            generated_content = response.text.strip()
            results_to_update.append({"index": task["index"], "content": generated_content})
            request_count += 1
            log.info(f"Đã tạo nội dung cho keyword: '{keyword}'")
        except Exception as e:
            log.error(f"Lỗi khi tạo nội dung cho keyword '{keyword}': {e}")
            log.info("Tạm nghỉ 5 giây trước khi thử lại keyword tiếp theo...")
            time.sleep(5)

    # 3. Cập nhật lại nội dung vào DataFrame
    if results_to_update:
        log.info(f"Đang cập nhật {len(results_to_update)} dòng vào file Excel...")
        for result in results_to_update:
            df.loc[result["index"], content_col] = result["content"]

        # 4. Lưu lại file Excel
        df.to_excel(file_path, index=False, engine="openpyxl")
        log.info(f"Đã cập nhật và lưu file thành công: {file_path}")