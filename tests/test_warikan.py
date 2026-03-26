"""割り勘計算のユニットテスト"""
import pytest
from app.warikan import calculate_warikan, parse_warikan_message, parse_record_message


class TestCalculateWarikan:
    def test_even_split(self):
        r = calculate_warikan(3000, 3)
        assert r.base_amount == 1000
        assert r.remainder == 0

    def test_odd_split(self):
        r = calculate_warikan(3100, 3)
        assert r.base_amount == 1033
        assert r.remainder == 1  # 1人だけ1034円

    def test_large_remainder(self):
        r = calculate_warikan(1001, 3)
        assert r.base_amount == 333
        assert r.remainder == 2  # 2人が334円

    def test_single_person(self):
        r = calculate_warikan(500, 1)
        assert r.base_amount == 500
        assert r.remainder == 0

    def test_zero_amount(self):
        r = calculate_warikan(0, 3)
        assert r.base_amount == 0

    def test_invalid_people(self):
        with pytest.raises(ValueError):
            calculate_warikan(1000, 0)


class TestParseWarikanMessage:
    def test_basic(self):
        assert parse_warikan_message("3000円 3人") == (3000, 3)

    def test_comma_in_amount(self):
        assert parse_warikan_message("10,000円 4人") == (10000, 4)

    def test_no_yen_mark(self):
        assert parse_warikan_message("5000 5人") == (5000, 5)

    def test_with_fullwidth_yen(self):
        assert parse_warikan_message("￥2000 2人") == (2000, 2)

    def test_unrelated_text(self):
        assert parse_warikan_message("こんにちは") is None


class TestParseRecordMessage:
    def test_basic(self):
        assert parse_record_message("記録 1500円 ランチ") == (1500, "ランチ")

    def test_no_label(self):
        result = parse_record_message("記録 2000円")
        assert result is not None
        assert result[0] == 2000

    def test_english(self):
        assert parse_record_message("add 3000円 dinner") == (3000, "dinner")
