from vision_adapter.protobuf_compat import patch_protobuf_get_prototype


def test_protobuf_get_prototype_patch_is_idempotent() -> None:
    patch_protobuf_get_prototype()
    patch_protobuf_get_prototype()
