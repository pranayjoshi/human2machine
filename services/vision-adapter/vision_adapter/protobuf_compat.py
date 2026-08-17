"""Keep MediaPipe working on protobuf 6, which removed MessageFactory.GetPrototype."""

from __future__ import annotations


def patch_protobuf_get_prototype() -> None:
    try:
        from google.protobuf import message_factory
    except Exception:
        return
    factory = getattr(message_factory, "MessageFactory", None)
    if factory is None or hasattr(factory, "GetPrototype"):
        return
    get_class = getattr(message_factory, "GetMessageClass", None)
    if get_class is None:
        return

    def _get_prototype(self, descriptor):  # noqa: ANN001, ARG001
        return get_class(descriptor)

    factory.GetPrototype = _get_prototype  # type: ignore[attr-defined]
