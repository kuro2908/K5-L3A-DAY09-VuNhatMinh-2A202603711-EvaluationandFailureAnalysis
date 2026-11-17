# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-014@11 (FM-05 pre_deducted)

Trace (rút gọn từ output của lệnh trên):
```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {... "claim_id": "C-014", "principal_scope": "owner_order_only" ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-515", "status": "delivered_late", ...}}}
   3 quote              {"amount_vnd": 150000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03", "DMG-04"], ...}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal           {"amount_vnd": 120000}
   6 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
  refund_vnd     ledger=90000    label=120000   <-- differs
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, report `reports/eval_seeded_regression.json`, run `E-seeded_regression-20261117-c329` |
| Triệu chứng | `pass_rate` FAIL (`proposal_mismatch`), `refund_amount_correct` FAIL (ledger 90.000 ≠ nhãn 120.000), `reply_matches_ledger` FAIL (reply nói 120.000đ, ledger chỉ có 90.000đ), `proposal_correct` FAIL (120.000 ≠ quote 150.000) |
| Bước sai đầu tiên | **Event 4 `refund_history`** `{"refund_count": 1, "refunded_vnd": 30000}`: agent tự tra lịch sử hoàn tiền để trừ. Event 5 `proposal {"amount_vnd": 120000}` là hệ quả trực tiếp của bước này |
| Vì sao là bước *đầu tiên* | Event 1 (handoff đúng claim, scope `owner_order_only`) và event 2 (đơn O-515 `delivered_late`, `visible=true`) đúng. Event 3 `quote` 150.000đ trùng với `proposal_amount` trong nhãn (150.000): giá chính sách đúng, và quote không có event `model_override` nên không phải FM-03. Từ event 4 agent mới làm việc vốn thuộc về host (trừ 30.000đ đã hoàn), nên host trừ lần hai: 150.000 − 30.000 − 30.000 = 90.000đ |
| Failure mode | **FM-05** pre_deducted (kéo theo FM-08: reply báo số agent tự tính chứ không phải số trong ledger) |
| Đối chứng | `fixed C-014@11`: event 3 `quote 150000`, **không có** `refund_history`/`proposal`, event 4 `reply` "đã hoàn 120.000đ"; ledger 120.000 = nhãn → PASS |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_c014_pre_deduct_is_caught_on_seeded_regression` chạy lại trial trên store mới, assert trace có `refund_history` + `proposal`, ledger = 90.000, và cả `refund_amount_correct`, `reply_matches_ledger`, `proposal_correct` đều False. `test_c014_passes_on_fixed` assert cả ba True trên `fixed`. Đã chạy: `13 passed` (`pytest -m student -k "lab9 and not advanced"`). Item E-014 cũng ghi `provenance.from_trace` trỏ về case này |
| Chưa chắc chắn | Trace không cho biết agent *vì sao* gọi `lookup_refund_history` (MockLLM không có lời giải thích); ta chỉ thấy hành vi. Với LLM thật, lỗi này có thể chỉ xuất hiện khi ticket nhắc "đã được hoàn trước đó" (như C-014). Trace cũng không chứng minh host luôn trừ đúng một lần: điều đó dựa vào `lab8.durability.issue_refund`, ngoài phạm vi Lab 9 |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
