# Draft: Torchcodec Windows Long-Term Fix

## Requirements (confirmed)
- User wants a complete work plan for the full torchcodec/Windows/ASR issue.
- Plan must cover both short-term hardening already applied and the long-term fix.
- Long-term fix should be safe to roll back if the replacement backend is not effective.
- The likely long-term direction is replacing transformers Whisper ASR with faster-whisper.

## Technical Decisions
- Short-term fix already applied: Windows dev extra no longer pulls torchcodec by default; ASR failure degrades more clearly; troubleshooting docs updated.
- Long-term migration should preserve existing OmniVoice public behavior.
- Rollback safety should be achieved through backend abstraction / dual-path support instead of hard replacement first.

## Research Findings
- Local ASR coupling is concentrated in OmniVoice/omnivoice/models/omnivoice.py: load_asr_model(), transcribe(), create_voice_clone_prompt().
- Current failure path is tied to transformers Whisper pipeline importing torchcodec during auto-transcription when ref_text is absent.
- faster-whisper can provide the needed transcript string without torchcodec, but has different model naming and segment-based output.
- Consumer impact extends to docs, CLI/demo behavior, and tests that exercise clone mode without explicit ref_text.

## Scope Boundaries
- INCLUDE: dependency strategy, ASR backend architecture, migration rollout, rollback strategy, tests/docs/verification, issue/PR communication.
- EXCLUDE: unrelated speech synthesis architecture changes, broader model quality tuning unrelated to ASR backend migration.

## Open Questions
- None blocking for plan generation; use reversible dual-backend rollout as default strategy.
