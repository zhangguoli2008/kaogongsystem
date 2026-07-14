"""Fixed Tencent QuestionSplitOCR invocation contract shared by API and provider."""

from typing import Final


API_NAME: Final[str] = "QuestionSplitOCR"
ACTION: Final[str] = "QuestionSplitOCR"
API_VERSION: Final[str] = "2018-11-19"
ENDPOINT: Final[str] = "ocr.tencentcloudapi.com"
USE_NEW_MODEL: Final[bool] = False
ENABLE_IMAGE_CROP: Final[bool] = True
ENABLE_ONLY_DETECT_BORDER: Final[bool] = False
