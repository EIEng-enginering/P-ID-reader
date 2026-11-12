"""The TrOCR training objective: labels = pieces + </s>, decoder input shifted right once, plain cross-entropy (no second shift, no <s>)."""
import pytest

from pid_reader.engineering.longterm import objective as O


class Tok:
    eos_token_id = 2

    def __call__(self, text, add_special_tokens=True, truncation=False):
        class R:
            input_ids = [10 + ord(c) % 7 for c in text]
        return R()


def test_label_ids_end_with_eos_and_never_start_with_bos():
    ids = O.label_ids(Tok(), "AB-1")
    assert ids[-1] == 2 and len(ids) == 5 and ids[0] != 0


def test_label_budget_is_enforced():
    with pytest.raises(ValueError):
        O.label_ids(Tok(), "X" * 120)


def test_loss_is_zero_for_a_model_that_predicts_the_next_label_token_and_large_if_misaligned():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    ids = [30, 31, 32, 2]
    vocab, pad, start = 40, 1, 2

    class Out:
        def __init__(self, logits):
            self.logits = logits

    class Stub(torch.nn.Module):
        """Logits at position k put all mass on the token that FOLLOWS decoder input k in the true sequence (start->30->31->32->2)."""
        nxt = {start: 30, 30: 31, 31: 32, 32: 2}

        def forward(self, pixel_values, decoder_input_ids):
            logits = torch.full((1, decoder_input_ids.shape[1], vocab), -20.0)
            for k, tok in enumerate(decoder_input_ids[0].tolist()):
                logits[0, k, self.nxt.get(tok, 0)] = 20.0
            return Out(logits)

    loss = O.sequence_loss(Stub(), torch.zeros(1, 3, 4, 4), ids, pad_token_id=pad, decoder_start_token_id=start)
    assert float(loss) < 1e-3
    wrong = O.sequence_loss(Stub(), torch.zeros(1, 3, 4, 4), [0] + ids, pad_token_id=pad, decoder_start_token_id=start)
    assert float(wrong) > 5                                     # a leading <s> the checkpoint never emits is heavily penalised
