# Auto Quiz

Tool desktop (Windows) tự động làm bài ôn luyện trên web, chạy ngầm bằng Chrome DevTools Protocol (CDP): không cần focus cửa sổ, vẫn làm việc khác bình thường.

> Chỉ dùng cho mục đích cá nhân/học tập. Hãy tuân thủ điều khoản sử dụng của trang bạn dùng.

## Tính năng

- Chạy ngầm qua CDP, không nháy focus, không dùng chuột/bàn phím thật.
- Hai chế độ:
  - `auto-quiz`: chọn đáp án ngẫu nhiên.
  - `auto-quiz-correct`: học đáp án đúng, lưu theo từng bài, tự sửa khi đáp án đã lưu bị sai.
- Khoá câu hỏi dựa trên ảnh minh hoạ và dòng câu hỏi, không phụ thuộc kích thước cửa sổ hay thứ tự câu.
- Tự lấy tên bài từ tên tab, dữ liệu tách riêng theo bài.
- Tự bấm Kết thúc luyện thi, rồi Luyện tất cả hoặc Luyện câu sai, lặp theo số lượt (1, 2, ..., Loop).
- Phím tắt toàn cục: `F8` Start/Stop, `Esc` Stop.

## Yêu cầu

- Windows 10/11
- Python 3.10+
- Google Chrome hoặc Microsoft Edge

## Cài đặt

```powershell
git clone https://github.com/<ten-ban>/auto-quiz.git
cd auto-quiz
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\venv\Scripts\pywin32_postinstall.py -install
```

## Chạy

Bấm đúp `run_cdp.bat`, hoặc:

```powershell
.\venv\Scripts\python.exe auto_quiz_cdp.py
```

## Cách dùng

1. Đóng hết Chrome đang dùng profile `chrome-profile` (kể cả trong khay hệ thống).
2. Bấm **Mở Chrome quiz**, đăng nhập và vào trang bài tập.
3. Bấm **Làm mới**, chọn mục `[Chrome nền] ...`, bấm **Test** để kiểm tra.
4. Chọn chế độ, số lượt, thời gian chờ rồi bấm **Start** (hoặc `F8`).
5. Dừng bằng **Stop** hoặc `Esc`. Không thu nhỏ (minimize) cửa sổ Chrome.

## Cấu hình

Các giá trị mặc định nằm ở khối `CẤU HÌNH MẶC ĐỊNH` đầu file `auto_quiz_cdp.py` (chế độ, số lượt, thời gian chờ, danh sách tên tab bị bỏ qua...).

## Cấu trúc

| File | Mô tả |
|---|---|
| `auto_quiz_cdp.py` | Tool chính, điều khiển thuần CDP |
| `auto_quiz_gui.py` | Bản cũ dựa trên nhận diện ảnh mẫu |
| `run_cdp.bat` | Mở nhanh tool CDP |
| `quiz_db.json` | Dữ liệu đáp án đã học (không đưa lên git) |
| `chrome-profile/` | Profile Chrome riêng (không đưa lên git) |

## Xử lý lỗi thường gặp

- **Không thấy mục `[Chrome nền]`**: Chrome đang chạy không có cổng debug. Đóng hết Chrome của profile này rồi bấm lại **Mở Chrome quiz**.
- **Không bấm được nút**: bấm **Test** xem tool tìm thấy nút ở toạ độ nào, gửi kèm `debug.png` khi báo lỗi.
- **`win32ui` báo thiếu DLL**: chạy `python .\venv\Scripts\pywin32_postinstall.py -install`.