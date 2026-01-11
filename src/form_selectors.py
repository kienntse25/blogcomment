COMMENT_TEXTAREAS = [
    # Standard WordPress
    "#comment", "textarea#comment", "textarea[name='comment']",
    "textarea[aria-label='comment' i]", "textarea[aria-label='Comment' i]",
    "textarea[id*='comment' i]",

    # WordPress themes (Divi, Elementor, Astra, GeneratePress, etc.)
    "#respond textarea", "#commentform textarea",
    ".comment-respond textarea", ".comments-area textarea",
    ".comment-form-comment textarea", "#comments textarea",
    ".comment-reply-form textarea", ".tf-comment-form textarea",
    ".bd-comments-area textarea", ".post-comments-form textarea",
    ".ht-comment-form textarea", ".rereadomments textarea",

    # Common form classes
    "textarea.comment-field", "textarea.comments-field",
    "textarea.wpcf7-textarea", "textarea.wp-editor-area",

    # Generic fallbacks
    "textarea",
    "textarea[placeholder*='Comment' i]",
    "textarea[placeholder*='Nhận xét' i]",
    "textarea[placeholder*='Bình luận' i]",
    "textarea[placeholder*='Viết bình luận' i]",
]

NAME_INPUTS = [
    # Standard WordPress
    "#author", "input#author", "input[name='author']",
    "input[name='name']", "input[aria-label='name' i]",
    "input[aria-label='Name' i]",

    # Common form fields
    "#user_name", "input#user_name",
    "#username", "input#username",
    "input.user-name", "input.author-name",
    "input[placeholder*='Name' i]", "input[placeholder*='Tên' i]",
    "input[placeholder*='Họ và tên' i]",

    # Generic
    "input[type='text']",
    "input[id*='author' i]", "input[id*='name' i]",
]

EMAIL_INPUTS = [
    # Standard WordPress
    "#email", "input#email", "input[name='email']",
    "input[type='email']",

    # Common form fields
    "#user_email", "input#user_email",
    "input.user-email", "input.author-email",
    "input[placeholder*='Email' i]", "input[placeholder*='mail' i]",

    # Generic fallbacks
    "input[type='email']",
    "input[id*='email' i]",
]

SUBMIT_BUTTONS = [
    # Standard
    "input[type='submit']", "button[type='submit']",
    "button[name='submit']",

    # WordPress themes
    "#commentform input[type='submit']",
    "#respond input[type='submit']",
    ".comment-respond input[type='submit']",
    ".form-submit input[type='submit']",

    # Buttons with common text
    "input[value*='Post' i]", "input[value*='Submit' i]",
    "input[value*='Gửi' i]", "input[value*='Bình luận' i]",
    "input[value*='Comment' i]",

    # Generic
    "button",
]
