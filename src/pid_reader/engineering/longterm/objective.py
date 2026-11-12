"""Training objective for TrOCR fine-tuning, defined explicitly.

Why this exists: with transformers 4.57.1 `VisionEncoderDecoderModel(..., labels=...)` returns a loss from the generic causal-LM loss, which shifts
the labels a second time although the model has already shifted its decoder inputs. On strings the pretrained model reads correctly that built-in
loss was 21.4, against 0.016 for a plain cross-entropy over the same logits and labels. The first programme trainer also prepended <s>, which this
checkpoint never emits. Both errors made the training signal wrong (loss near 6 for a model that reads 86 % of the crops exactly).
Convention used here (the one the checkpoint generates with): labels = piece ids + </s>, decoder input = [</s>] + labels[:-1].
"""


def label_ids(tokenizer, text, limit=96):
    ids = list(tokenizer(text, add_special_tokens=False, truncation=False).input_ids) + [tokenizer.eos_token_id]
    if len(ids) > limit:
        raise ValueError("Label token budget exceeded")
    return ids


def sequence_loss(model, pixel_values, ids, *, pad_token_id, decoder_start_token_id):
    """Plain cross-entropy over the decoder logits for one label sequence. `ids` is a list of token ids."""
    import torch
    from transformers.models.vision_encoder_decoder.modeling_vision_encoder_decoder import shift_tokens_right
    labels = torch.tensor([ids])
    decoder_input_ids = shift_tokens_right(labels, pad_token_id, decoder_start_token_id)
    logits = model(pixel_values=pixel_values, decoder_input_ids=decoder_input_ids).logits
    return torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), labels.reshape(-1))
