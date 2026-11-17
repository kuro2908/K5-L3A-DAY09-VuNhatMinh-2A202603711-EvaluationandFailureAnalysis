# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`. Lớp dương (positive) là **FAIL**, vì việc của judge là tìm lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (`PASS floors`) | **dùng** (chỉ cho giọng văn, non-blocking ở mức trial) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt**: κ < 0.6, R < 0.7 (`FAIL floors`) | **loại** |

Ma trận nhầm lẫn (FAIL = dương):
- tone_ok: tp 24 · fp 4 · fn 6 · tn 66. Tỉ lệ FAIL quan sát 0.28, Rogan-Gladen hiệu chỉnh thành **0.30**.
- helpful: tp 9 · fp 0 · fn 21 · tn 70. Tỉ lệ FAIL quan sát 0.09, nhưng hiệu chỉnh ra **0.30**. Judge thấy chưa tới 1/3 số lỗi thật.

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em" + "nha" là quá suồng sã với khách. Rubric thêm: *xưng hô phải là "LogiX" / "anh/chị"; "em", "bạn", "nha", "nhé" ⇒ FAIL*, kèm 1 ví dụ âm |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | **Người** | Cùng lỗi xưng "bạn". Judge đọc nhầm "thân thiện" thành "đúng giọng". Dùng chung quy tắc xưng hô ở #1 |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Mở đầu lịch sự nhưng nội dung ra lệnh. Rubric thêm: *chấm cả câu, không chấm theo từ mở đầu; câu mệnh lệnh cấm khách liên hệ ⇒ FAIL* |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric bỏ yêu cầu ngầm này: *không bắt buộc xin lỗi khi yêu cầu đã được giải quyết; ngắn mà đủ ý ⇒ PASS* |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | Judge phạt vì có từ tiếng Anh, trong khi CS LogiX cho phép "refund". Rubric thêm whitelist thuật ngữ: *refund, ship, voucher không bị trừ điểm* |
| 6 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge helpful không thấy ledger nên không thể biết số tiền sai. Không sửa bằng rubric được: số tiền chuyển sang grader code `reply_matches_ledger` (FM-08) |
| 7 | HL-016 (xin lỗi dài, "đã hoàn 55.000đ", ledger 35.000đ) | PASS | FAIL | **Người** | Câu dài, nhiều lời xin lỗi khiến judge chấm "helpful", nhưng số tiền vẫn sai. Đây là thiên lệch theo độ dài (verbosity bias) |
| 8 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Sai xưng hô và không nói số tiền. Đây là phần việc của judge tone, không phải helpful |

Trong 21 false negative của judge helpful có **18 lỗi "sai tiền"** và 3 lỗi "sai xưng hô". 9 lỗi judge bắt được đều thuộc loại khác (giọng cụt 4, không hỏi lại mã đơn 3, lạc đề 2). Nghĩa là judge **không bắt được lỗi sai tiền nào (0/18)**.

## Kết luận
- **helpful bị loại** làm gate. Recall 0.30 (fn = 21/30) nghĩa là judge cho qua 70% câu trả lời tệ, và κ = 0.375 < 0.6. Precision 1.0 chỉ cho thấy judge rất "dễ tính": nó hiếm khi nói FAIL (9/100). Nếu dùng nó làm gate, tỉ lệ lỗi báo cáo là 0.09 trong khi tỉ lệ thật khoảng 0.30 (Rogan-Gladen). Ngoài ra lỗi nó bỏ sót chủ yếu là sai tiền, loại lỗi mà quy tắc nói **luôn chấm bằng code**. Vì vậy nhóm thêm `reply_matches_ledger` (đọc ledger) thay vì sửa judge.
- **tone_ok dùng được** cho tiêu chí giọng văn: κ 0.757, P 0.857, R 0.80 đều vượt sàn. Khi báo cáo tỉ lệ lỗi giọng văn, dùng giá trị đã hiệu chỉnh 0.30, không dùng 0.28. 5 bất đồng ở trên có 3 FN (xưng hô suồng sã, giọng ra lệnh) và 2 FP (bắt xin lỗi, cấm tiếng Anh). Cả năm đều sửa được bằng các quy tắc rubric ghi ở cột cuối.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (CSV có sẵn kết quả judge). Sau khi sửa rubric phải chấm lại trên một tập nhãn người **mới**, làm held-out thật, rồi mới coi số liệu trên là đáng tin. Tiền và approval không bao giờ giao cho judge.
