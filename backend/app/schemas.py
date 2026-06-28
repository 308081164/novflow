from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str = "作者"


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    deepseek_configured: bool = False

    class Config:
        from_attributes = True


class UserSettingsIn(BaseModel):
    deepseek_api_key: Optional[str] = None
    display_name: Optional[str] = None
    jimeng_api_key: Optional[str] = None
    jimeng_base_url: Optional[str] = None
    jimeng_model: Optional[str] = None


class UserSettingsOut(BaseModel):
    display_name: str
    deepseek_configured: bool
    deepseek_api_key_masked: str = ""
    jimeng_configured: bool = False
    jimeng_api_key_masked: str = ""
    jimeng_base_url: str = ""
    jimeng_model: str = ""


class BookCreate(BaseModel):
    title: str
    blurb: str = ""
    platform: str = "fanqie"
    template_id: str = "blank"
    genre: str = ""
    premise: str = ""
    target_chapters: int = 300
    words_per_chapter: int = 2000


class BookOut(BaseModel):
    id: int
    title: str
    blurb: str
    platform: str
    template_id: str
    genre: str = ""
    premise: str = ""
    setup_step: int = 5
    target_chapters: int
    words_per_chapter: int
    planned_chapters: int = 0
    outline_planned_count: int = 0
    chapter_count: int = 0
    written_count: int = 0
    approved_count: int = 0
    cover_image_url: str = ""

    class Config:
        from_attributes = True


class BookImportOut(BookOut):
    imported_characters: int = 0
    has_worldview: bool = False
    has_outline: bool = False
    has_writing_prefs: bool = False
    ai_adapted: bool = False
    adapt_warning: str = ""


class BookSetupUpdate(BaseModel):
    title: Optional[str] = None
    blurb: Optional[str] = None
    genre: Optional[str] = None
    premise: Optional[str] = None
    setup_step: Optional[int] = None


class BookResourcesOut(BaseModel):
    author_preferences: str = ""
    has_author_preferences: bool = False
    writing_rules: str = ""
    corpus: str = ""
    has_writing_rules: bool = False


class BookResourcesIn(BaseModel):
    author_preferences: Optional[str] = None
    writing_rules: Optional[str] = None
    corpus: Optional[str] = None


class SyncSettingsOut(BaseModel):
    cards_applied: int = 0
    outline_chapters: int = 0
    outline_planned_count: int = 0
    planned_chapters: int = 0
    characters_synced: int = 0
    duplicates_removed: int = 0
    errors: list[str] = Field(default_factory=list)
    target_chapters: Optional[int] = None


class WorldviewOut(BaseModel):
    id: int
    book_id: int
    era: str
    setting: str
    tone: str
    timeline_text: str
    taboos: str
    content: str

    class Config:
        from_attributes = True


class WorldviewIn(BaseModel):
    era: str = ""
    setting: str = ""
    tone: str = ""
    timeline_text: str = ""
    taboos: str = ""
    content: str = ""


class CharacterIn(BaseModel):
    name: str
    role: str = "support"
    summary: str = ""
    voice_notes: str = ""
    content: str = ""
    arc_json: dict = Field(default_factory=dict)


class CharacterOut(CharacterIn):
    id: int
    book_id: int

    class Config:
        from_attributes = True


class CharacterAiIn(BaseModel):
    hint: str = ""


class OutlineAiIn(BaseModel):
    start_chapter: int = 1
    count: int = 10


class ChapterPlanOut(BaseModel):
    id: int
    chapter_no: int
    title: str
    mode: str
    scene: str
    plot_points: str
    comedy_core: str
    pov_switch: bool
    character_names: str
    meta_json: dict = Field(default_factory=dict)
    status: str = "planned"

    class Config:
        from_attributes = True


class ChapterPlanUpdate(BaseModel):
    title: Optional[str] = None
    mode: Optional[str] = None
    scene: Optional[str] = None
    plot_points: Optional[str] = None
    comedy_core: Optional[str] = None
    pov_switch: Optional[bool] = None
    character_names: Optional[str] = None
    meta_json: Optional[dict] = None


class ChapterOut(BaseModel):
    id: int
    chapter_no: int
    title: str
    content: str
    word_count: int
    status: str
    approved: bool = False
    updated_at: datetime

    class Config:
        from_attributes = True


class ChapterSave(BaseModel):
    content: str
    title: Optional[str] = None


class LintCheckIn(BaseModel):
    content: str
    include_ai: bool = False


class FixDraftIn(BaseModel):
    content: str


class FixIssueIn(BaseModel):
    content: str
    rule_id: str
    line_no: int = 0


class GenerateIn(BaseModel):
    instruction: str = ""


class ExpandIn(BaseModel):
    extra_words: int = 500
    instruction: str = ""


class LintIssueOut(BaseModel):
    id: Optional[int] = None
    rule_id: str
    severity: str
    line_no: int
    excerpt: str = ""
    snippet: str = ""
    message: str
    auto_fixable: bool = False
    blocking: bool = True

    class Config:
        from_attributes = True


class LintReport(BaseModel):
    word_count: int
    issues: list[LintIssueOut]
    error_count: int
    warn_count: int
    passed: bool = True


class FixDraftOut(BaseModel):
    content: str
    lint: LintReport
    fixed_count: int = 0


class JobOut(BaseModel):
    id: int
    job_type: str
    status: str
    chapter_no: int
    result_content: str = ""
    error: str = ""

    class Config:
        from_attributes = True


class WriteAgentHistoryItem(BaseModel):
    role: str
    content: str


class WriteAgentChatIn(BaseModel):
    message: str
    chapter_no: int
    draft_content: str | None = None
    history: list[WriteAgentHistoryItem] = Field(default_factory=list)
    input_text: str | None = None
    quote: str | None = None
    lint_issues: list[dict] = Field(default_factory=list)
    resend_from_message_id: int | None = None


class WriteAgentEditOut(BaseModel):
    chapter_no: int
    title: str | None = None
    content: str
    reason: str = ""


class WriteAgentAppliedOut(BaseModel):
    chapter_no: int
    title: str = ""
    word_count: int = 0
    previous_content: str = ""


class WriteAgentRevertSnapshotOut(BaseModel):
    chapter_no: int
    title: str = ""
    content: str = ""


class WriteAgentRevertIn(BaseModel):
    snapshots: list[WriteAgentRevertSnapshotOut] = Field(default_factory=list)


class SetupCardOut(BaseModel):
    id: str
    type: str
    title: str = ""
    status: str = "draft"
    data: dict = Field(default_factory=dict)


class SetupActionOut(BaseModel):
    type: str
    label: str
    chapter_no: int | None = None
    description: str | None = None


class WriteAgentContextStatus(BaseModel):
    estimated_chars: int
    estimated_tokens: int
    system_chars: int = 0
    history_chars: int = 0
    message_count: int
    active_message_count: int
    warn: bool = False
    suggest_compress: bool = False
    has_summary: bool = False


class WriteAgentMessageOut(BaseModel):
    id: int
    role: str
    content: str
    cards: list[SetupCardOut] = Field(default_factory=list)
    actions: list[SetupActionOut] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class WriteAgentMessagesOut(BaseModel):
    session_id: str
    messages: list[WriteAgentMessageOut]
    context_status: WriteAgentContextStatus | None = None


class WriteAgentNewSessionOut(BaseModel):
    session_id: str
    messages: list[WriteAgentMessageOut]
    context_status: WriteAgentContextStatus | None = None


class WriteAgentCompressOut(BaseModel):
    ok: bool
    message: str
    archived_count: int = 0
    summary_message: WriteAgentMessageOut | None = None
    context_status: WriteAgentContextStatus
    messages: list[WriteAgentMessageOut] = Field(default_factory=list)


class GeneratedImageOut(BaseModel):
    id: int | None = None
    url: str
    object_key: str = ""
    kind: str = "cover"
    prompt: str = ""
    parent_id: int | None = None
    character_id: int | None = None
    created_at: str | None = None
    is_active: bool = False


class CharacterPortraitActiveIn(BaseModel):
    object_key: str


class WriteAgentChatOut(BaseModel):
    reply: str
    edits: list[WriteAgentEditOut] = Field(default_factory=list)
    applied: list[WriteAgentAppliedOut] = Field(default_factory=list)
    revert_snapshots: list[WriteAgentRevertSnapshotOut] = Field(default_factory=list)
    cards: list[SetupCardOut] = Field(default_factory=list)
    card_applied: list[dict] = Field(default_factory=list)
    actions: list[SetupActionOut] = Field(default_factory=list)
    images: list[GeneratedImageOut] = Field(default_factory=list)
    user_message: WriteAgentMessageOut | None = None
    assistant_message: WriteAgentMessageOut | None = None
    session_id: str = ""
    context_status: WriteAgentContextStatus | None = None


class SetupMessageOut(BaseModel):
    id: int
    role: str
    content: str
    cards: list[SetupCardOut] = Field(default_factory=list)
    actions: list[SetupActionOut] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class SetupChatIn(BaseModel):
    message: str = Field(min_length=1)


class SetupApplyIn(BaseModel):
    card: SetupCardOut


class SetupContextOut(BaseModel):
    book: BookOut
    snapshot: dict
    messages: list[SetupMessageOut]


class SetupChatTurnOut(BaseModel):
    user_message: SetupMessageOut
    assistant_message: SetupMessageOut
    applied: list[dict] = Field(default_factory=list)
    book: BookOut
    snapshot: dict


class CoverGenerateIn(BaseModel):
    prompt: str | None = None


class CharacterImageGenerateIn(BaseModel):
    prompt: str | None = None
    parent_object_key: str | None = None


class IllustrationGenerateIn(BaseModel):
    passage: str | None = None
    prompt: str | None = None
    parent_id: int | None = None
    character_ids: list[int] = Field(default_factory=list)


class ImageRefineIn(BaseModel):
    kind: str = "cover"
    prompt: str
    parent_object_key: str | None = None
    parent_id: int | None = None
    character_id: int | None = None
    chapter_no: int | None = None


class JimengTestIn(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
