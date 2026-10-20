"""Orca-style token-wise batching for the pinned, full-attention Qwen2 model.

Linear/normalization/MLP operations share a flattened token dimension. Attention
and KV state remain request-local; no padding or cross-request attention occurs.
This is a CPU implementation of the mechanism, not Orca's distributed GPU engine.
"""
from __future__ import annotations


def forward_pieces(model, pieces, emits):
    """Return last-position logits per (input_ids, request_cache) piece.

    Pieces may combine a decode token and arbitrary-length prefill chunks.
    Callers own admission, cancellation and retirement at iteration boundaries.
    """
    import torch
    from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS
    from transformers.models.qwen2.modeling_qwen2 import apply_rotary_pos_emb, eager_attention_forward

    core = model.model
    if model.config.model_type != "qwen2" or core.has_sliding_layers:
        raise ValueError("selective execution supports full-attention Qwen2 only")
    sizes = [ids.shape[-1] for ids, _ in pieces]
    past = [cache.get_seq_length() for _, cache in pieces]
    ids = torch.cat([ids for ids, _ in pieces], dim=1)
    positions = torch.cat([torch.arange(start, start + size) for start, size in zip(past, sizes)])[None]
    hidden = core.embed_tokens(ids)
    cos, sin = core.rotary_emb(hidden, positions)
    masks = []
    for start, size in zip(past, sizes):
        # SDPA handles initial causal prefill and single-token decode directly.
        # Cached multi-token chunks require a bottom-right aligned causal mask.
        if start and size > 1:
            allowed = torch.arange(start + size)[None, :] <= torch.arange(start, start + size)[:, None]
            mask = torch.zeros((size, start + size), dtype=hidden.dtype)
            mask.masked_fill_(~allowed, torch.finfo(hidden.dtype).min)
            masks.append(mask[None, None])
        else:
            masks.append(None)

    for layer in core.layers:
        residual = hidden
        normalized = layer.input_layernorm(hidden)
        attn = layer.self_attn
        shape = (1, sum(sizes), -1, attn.head_dim)
        query = attn.q_proj(normalized).view(shape).transpose(1, 2)
        key = attn.k_proj(normalized).view(shape).transpose(1, 2)
        value = attn.v_proj(normalized).view(shape).transpose(1, 2)
        query, key = apply_rotary_pos_emb(query, key, cos, sin)
        interface = ALL_ATTENTION_FUNCTIONS.get_interface(model.config._attn_implementation, eager_attention_forward)
        outputs = []
        for q, k, v, (_, cache), mask in zip(query.split(sizes, dim=2), key.split(sizes, dim=2),
                                            value.split(sizes, dim=2), pieces, masks):
            k, v = cache.update(k, v, attn.layer_idx)
            output, _ = interface(attn, q, k, v, mask, dropout=0.0, scaling=attn.scaling,
                                  sliding_window=None)
            outputs.append(output.reshape(1, q.shape[2], -1))
        hidden = residual + attn.o_proj(torch.cat(outputs, dim=1))
        hidden = hidden + layer.mlp(layer.post_attention_layernorm(hidden))

    # Intermediate prompt positions never need vocabulary-sized logits.
    last = (torch.tensor(sizes).cumsum(0) - 1)[torch.tensor(emits)]
    logits = model.lm_head(core.norm(hidden[:, last, :]))[0] if len(last) else []
    rows = iter(logits)
    return [next(rows) if emit else None for emit in emits]
