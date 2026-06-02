from watermark import SYSTEMATIC_TEMPLATE_OUTPUT, add_watermark, find_watermarks, has_valid_watermark


def test_watermark_helpers():
    payload = add_watermark({"hello": "world"}, SYSTEMATIC_TEMPLATE_OUTPUT)
    assert has_valid_watermark(payload)
    assert SYSTEMATIC_TEMPLATE_OUTPUT in find_watermarks(payload)
