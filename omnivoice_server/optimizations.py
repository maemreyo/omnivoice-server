"""Optional inference optimizations that are independent of OmniVoice versions."""

from __future__ import annotations

import math
from types import MethodType

import torch


@torch.inference_mode()
def _generate_iterative_split(self, task, gen_config):
    """Generate CFG branches separately, avoiding padded ``2B`` tensors."""
    inputs = [
        self._prepare_inference_inputs(
            task.texts[i],
            task.target_lens[i],
            task.ref_texts[i],
            task.ref_audio_tokens[i],
            task.langs[i],
            task.instructs[i],
            gen_config.denoise,
        )
        for i in range(task.batch_size)
    ]
    c_lens = [item["input_ids"].size(2) for item in inputs]
    max_c_len = max(c_lens)
    max_u_len = max(task.target_lens)
    codebooks = self.config.num_audio_codebook
    pad_id = self.config.audio_mask_id

    cond_ids = torch.full(
        (task.batch_size, codebooks, max_c_len), pad_id, dtype=torch.long, device=self.device
    )
    uncond_ids = torch.full(
        (task.batch_size, codebooks, max_u_len), pad_id, dtype=torch.long, device=self.device
    )
    cond_audio_mask = torch.zeros(
        (task.batch_size, max_c_len), dtype=torch.bool, device=self.device
    )
    uncond_audio_mask = torch.zeros(
        (task.batch_size, max_u_len), dtype=torch.bool, device=self.device
    )
    cond_attention_mask = torch.zeros(
        (task.batch_size, 1, max_c_len, max_c_len), dtype=torch.bool, device=self.device
    )
    uncond_attention_mask = torch.zeros(
        (task.batch_size, 1, max_u_len, max_u_len), dtype=torch.bool, device=self.device
    )

    for i, item in enumerate(inputs):
        c_len, u_len = c_lens[i], task.target_lens[i]
        cond_ids[i, :, :c_len] = item["input_ids"]
        cond_audio_mask[i, :c_len] = item["audio_mask"]
        cond_attention_mask[i, :, :c_len, :c_len] = True
        uncond_ids[i, :, :u_len] = item["input_ids"][..., -u_len:]
        uncond_audio_mask[i, :u_len] = item["audio_mask"][..., -u_len:]
        uncond_attention_mask[i, :, :u_len, :u_len] = True
        if max_u_len > u_len:
            pad_diag = torch.arange(u_len, max_u_len, device=self.device)
            uncond_attention_mask[i, :, pad_diag, pad_diag] = True

    tokens = torch.full(
        (task.batch_size, codebooks, max_u_len), pad_id, dtype=torch.long, device=self.device
    )
    from .vendor.omnivoice_012 import _get_time_steps, _gumbel_sample

    schedule_steps = _get_time_steps(
        t_start=0.0,
        t_end=1.0,
        num_step=gen_config.num_step + 1,
        t_shift=gen_config.t_shift,
    ).tolist()
    schedules = []
    for target_len in task.target_lens:
        remaining = target_len * codebooks
        schedule = []
        for step in range(gen_config.num_step):
            count = (
                remaining
                if step == gen_config.num_step - 1
                else min(
                    math.ceil(
                        codebooks
                        * target_len
                        * (schedule_steps[step + 1] - schedule_steps[step])
                    ),
                    remaining,
                )
            )
            schedule.append(int(count))
            remaining -= int(count)
        schedules.append(schedule)

    layer_ids = torch.arange(codebooks, device=self.device).view(1, -1, 1)
    for step in range(gen_config.num_step):
        cond_logits = self(
            input_ids=cond_ids,
            audio_mask=cond_audio_mask,
            attention_mask=cond_attention_mask,
        ).logits
        uncond_logits = self(
            input_ids=uncond_ids,
            audio_mask=uncond_audio_mask,
            attention_mask=uncond_attention_mask,
        ).logits
        for i, target_len in enumerate(task.target_lens):
            count = schedules[i][step]
            if count <= 0:
                continue
            c_len = c_lens[i]
            c_logits = cond_logits[i : i + 1, :, c_len - target_len : c_len, :].float()
            u_logits = uncond_logits[i : i + 1, :, :target_len, :].float()
            predictions, scores = self._predict_tokens_with_scoring(
                c_logits, u_logits, gen_config
            )
            scores = scores - layer_ids * gen_config.layer_penalty_factor
            if gen_config.position_temperature > 0.0:
                scores = _gumbel_sample(scores, gen_config.position_temperature)
            sample = tokens[i : i + 1, :, :target_len]
            scores.masked_fill_(sample != pad_id, -float("inf"))
            _, topk = torch.topk(scores.flatten(), count)
            flat = sample.flatten()
            flat[topk] = predictions.flatten()[topk]
            sample.copy_(flat.view_as(sample))
            cond_ids[i, :, c_len - target_len : c_len] = sample[0]
            uncond_ids[i, :, :target_len] = sample[0]

    return [tokens[i, :, : task.target_lens[i]] for i in range(task.batch_size)]


def apply_split_cfg_batch(model) -> None:
    """Patch a loaded model to use separate, right-sized CFG forwards."""
    model._generate_iterative = MethodType(_generate_iterative_split, model)
    model._omnivoice_server_split_cfg_batch = True
