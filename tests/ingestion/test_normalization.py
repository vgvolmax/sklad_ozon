from backend.ingestion.normalization import (
    normalize_cluster_label, normalize_header, normalize_text, resolve_cluster_id,
)


def test_text_and_header_normalization_is_harmless():
    assert normalize_text("\ufeff  Cafe\u0301\u00a0  склад ") == "Café склад"
    assert normalize_text(None) == ""
    assert normalize_header("\ufeff  Артикул\u00a0 продавца ") == "артикул продавца"
    assert normalize_cluster_label("  МОСКВА  ") == "МОСКВА"


def test_cluster_resolution_uses_only_explicit_maps_and_manual_wins():
    value, diagnostic = resolve_cluster_id("Москва Север", {}, {})
    assert value is None
    assert diagnostic.code == "UNRESOLVED_CLUSTER"
    assert resolve_cluster_id("МОСКВА", {"МОСКВА": "cluster-moscow"}, {}) == ("cluster-moscow", None)
    assert resolve_cluster_id(
        "МОСКВА",
        {"МОСКВА": "cluster-moscow-imported"},
        {"МОСКВА": "cluster-moscow-manual"},
    ) == ("cluster-moscow-manual", None)
