import logging
import base64
import math
import re
from typing import Optional, List, Tuple, Dict
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from google import genai

from app.config import settings
from app.models.schemas import SceneElement
from app.services.model_selector import model_selector

logger = logging.getLogger(__name__)

# Color name to RGB mapping for scene elements
COLOR_MAP: Dict[str, Tuple[int, int, int]] = {
    "red": (220, 50, 50), "blue": (50, 100, 220), "green": (50, 180, 80),
    "yellow": (230, 210, 50), "white": (230, 230, 230), "black": (40, 40, 40),
    "silver": (180, 180, 195), "gray": (130, 130, 140), "grey": (130, 130, 140),
    "orange": (240, 150, 30), "brown": (140, 90, 50), "purple": (140, 60, 180),
    "gold": (210, 180, 50), "tan": (190, 170, 130), "beige": (200, 190, 160),
    "maroon": (128, 0, 0), "navy": (30, 40, 120), "teal": (0, 128, 128),
    "dark": (60, 60, 70), "light": (200, 200, 210),
}

# Default colors per element type
TYPE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "vehicle": (70, 130, 220), "person": (220, 160, 60),
    "object": (120, 180, 120), "location_feature": (160, 140, 180),
}

# Type icons for legend
TYPE_ICONS: Dict[str, str] = {
    "vehicle": "▬", "person": "●", "object": "◆", "location_feature": "▣",
}


def _resolve_color(element: SceneElement) -> Tuple[int, int, int]:
    """Resolve an element's display color from its color field or type default."""
    if element.color:
        c = element.color.lower().strip()
        for name, rgb in COLOR_MAP.items():
            if name in c:
                return rgb
    return TYPE_COLORS.get(element.type, (150, 150, 150))


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load a TrueType font, fall back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


class ImageGenerationService:
    """Service for generating scene diagram images."""

    def __init__(self):
        self.client = None
        self.model = None
        self._initialize_client()

    def _initialize_client(self):
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                self.model = settings.gemini_vision_model
                logger.info("Gemini image generation client initialized")
            else:
                logger.warning("GOOGLE_API_KEY not set, image generation not available")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.client = None
            self.model = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_scene_image(
        self,
        scene_description: str,
        elements: List[SceneElement] = [],
        is_correction: bool = False,
        previous_description: Optional[str] = None,
    ) -> Optional[bytes]:
        try:
            image = self._create_scene_diagram(scene_description, elements)
            buf = BytesIO()
            image.save(buf, format="PNG")
            logger.info("Generated scene diagram image")
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Failed to generate scene image: {e}")
            return None

    # ------------------------------------------------------------------
    # Scene diagram renderer
    # ------------------------------------------------------------------

    def _create_scene_diagram(
        self, scene_description: str, elements: List[SceneElement]
    ) -> Image.Image:
        W, H = 1000, 750
        img = Image.new("RGB", (W, H), (18, 22, 30))
        draw = ImageDraw.Draw(img)

        font_title = _get_font(18)
        font_label = _get_font(13)
        font_small = _get_font(11)
        font_desc = _get_font(10)

        # --- background grid (road/intersection) ---
        self._draw_road_grid(draw, W, H)

        # --- header bar ---
        draw.rectangle([(0, 0), (W, 50)], fill=(12, 14, 20))
        draw.text((14, 14), "🔍 CRIME SCENE DIAGRAM", fill=(0, 212, 255), font=font_title)
        draw.text((W - 200, 18), "WitnessReplay", fill=(100, 110, 130), font=font_small)

        # --- scene description area ---
        desc_y = 56
        draw.rectangle([(0, desc_y), (W, desc_y + 44)], fill=(14, 16, 24, 200))
        wrapped = self._wrap_text(scene_description, 130)
        for i, line in enumerate(wrapped[:2]):
            draw.text((14, desc_y + 4 + i * 18), line, fill=(180, 190, 210), font=font_desc)

        # --- diagram area ---
        diagram_top = 104
        diagram_bottom = H - 120
        diagram_h = diagram_bottom - diagram_top

        # Place elements in the diagram area
        placements: List[Tuple[SceneElement, int, int, Tuple[int, int, int]]] = []
        n = max(len(elements), 1)

        for idx, elem in enumerate(elements):
            color = _resolve_color(elem)
            # Distribute elements across the diagram area
            cx, cy = self._compute_position(elem, idx, n, W, diagram_top, diagram_h)
            placements.append((elem, cx, cy, color))

        # Draw elements
        for elem, cx, cy, color in placements:
            self._draw_element(draw, elem, cx, cy, color, font_label, font_small)

        # --- legend ---
        self._draw_legend(draw, elements, W, H, font_label, font_small)

        # --- border ---
        draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(0, 212, 255, 80), width=2)

        return img

    # ------------------------------------------------------------------
    # Background
    # ------------------------------------------------------------------

    def _draw_road_grid(self, draw: ImageDraw.Draw, W: int, H: int):
        """Draw road / intersection grid pattern."""
        grid_color = (30, 36, 48)
        line_color = (40, 48, 60)

        # Grid lines
        for x in range(0, W, 60):
            draw.line([(x, 0), (x, H)], fill=grid_color, width=1)
        for y in range(0, H, 60):
            draw.line([(0, y), (W, y)], fill=line_color, width=1)

        # Main road (horizontal)
        road_y = H // 2 - 30
        draw.rectangle([(0, road_y), (W, road_y + 80)], fill=(35, 40, 52))
        # Center dashes
        for x in range(0, W, 40):
            draw.rectangle([(x, road_y + 38), (x + 20, road_y + 42)], fill=(80, 85, 60))
        # Road edges
        draw.line([(0, road_y), (W, road_y)], fill=(60, 65, 50), width=2)
        draw.line([(0, road_y + 80), (W, road_y + 80)], fill=(60, 65, 50), width=2)

        # Cross road (vertical)
        road_x = W // 2 - 30
        draw.rectangle([(road_x, 100), (road_x + 80, H - 120)], fill=(35, 40, 52))
        for y in range(100, H - 120, 40):
            draw.rectangle([(road_x + 38, y), (road_x + 42, y + 20)], fill=(80, 85, 60))
        draw.line([(road_x, 100), (road_x, H - 120)], fill=(60, 65, 50), width=2)
        draw.line([(road_x + 80, 100), (road_x + 80, H - 120)], fill=(60, 65, 50), width=2)

        # Intersection fill
        draw.rectangle([(road_x, road_y), (road_x + 80, road_y + 80)], fill=(40, 45, 55))

        # Sidewalk hints
        sw = (48, 50, 58)
        draw.rectangle([(0, road_y - 12), (road_x, road_y)], fill=sw)
        draw.rectangle([(road_x + 80, road_y - 12), (W, road_y)], fill=sw)
        draw.rectangle([(0, road_y + 80), (road_x, road_y + 92)], fill=sw)
        draw.rectangle([(road_x + 80, road_y + 80), (W, road_y + 92)], fill=sw)

    # ------------------------------------------------------------------
    # Element drawing
    # ------------------------------------------------------------------

    def _compute_position(
        self, elem: SceneElement, idx: int, n: int,
        W: int, diagram_top: int, diagram_h: int,
    ) -> Tuple[int, int]:
        """Compute (cx, cy) for an element based on position text or index."""
        margin_x, margin_y = 90, 40
        usable_w = W - 2 * margin_x
        usable_h = diagram_h - 2 * margin_y

        # Try to parse position keywords
        if elem.position:
            pos = elem.position.lower()
            fx = 0.5
            fy = 0.5
            if "left" in pos:
                fx = 0.15
            elif "right" in pos:
                fx = 0.85
            if "top" in pos or "north" in pos:
                fy = 0.15
            elif "bottom" in pos or "south" in pos:
                fy = 0.85
            if "center" in pos or "middle" in pos or "intersection" in pos:
                fx, fy = 0.5, 0.5
            if "near" in pos or "close" in pos:
                fx = max(0.3, min(0.7, fx))
                fy = max(0.3, min(0.7, fy))
            # Add small jitter to avoid perfect overlap
            jitter_x = ((idx * 37) % 11 - 5) * 8
            jitter_y = ((idx * 53) % 11 - 5) * 8
            cx = int(margin_x + fx * usable_w + jitter_x)
            cy = int(diagram_top + margin_y + fy * usable_h + jitter_y)
        else:
            # Distribute in a spiral-like pattern
            cols = max(int(math.ceil(math.sqrt(n))), 2)
            row = idx // cols
            col = idx % cols
            cx = int(margin_x + (col + 0.5) / cols * usable_w)
            cy = int(diagram_top + margin_y + (row + 0.5) / max(((n - 1) // cols + 1), 1) * usable_h)

        # Clamp
        cx = max(margin_x, min(W - margin_x, cx))
        cy = max(diagram_top + margin_y, min(diagram_top + diagram_h - margin_y, cy))
        return cx, cy

    def _draw_element(
        self, draw: ImageDraw.Draw, elem: SceneElement,
        cx: int, cy: int, color: Tuple[int, int, int],
        font_label: ImageFont.FreeTypeFont, font_small: ImageFont.FreeTypeFont,
    ):
        etype = elem.type.lower()

        if etype == "vehicle":
            self._draw_vehicle(draw, cx, cy, color, elem, font_label, font_small)
        elif etype == "person":
            self._draw_person(draw, cx, cy, color, elem, font_label, font_small)
        else:
            self._draw_object(draw, cx, cy, color, elem, font_label, font_small)

    def _draw_vehicle(self, draw, cx, cy, color, elem, font_label, font_small):
        w, h = 60, 30
        # Determine if truck/large
        desc_l = (elem.description or "").lower() + (elem.size or "").lower()
        if any(k in desc_l for k in ["truck", "suv", "van", "bus", "large"]):
            w, h = 75, 35
        # Shadow
        draw.rectangle([(cx - w // 2 + 3, cy - h // 2 + 3), (cx + w // 2 + 3, cy + h // 2 + 3)],
                        fill=(0, 0, 0, 80))
        # Body
        draw.rectangle([(cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2)],
                        fill=color, outline=(255, 255, 255, 120), width=2)
        # Windshield
        draw.rectangle([(cx - w // 4, cy - h // 2 + 3), (cx + w // 4, cy - h // 2 + 8)],
                        fill=(180, 210, 230))
        # Wheels
        for dx in [-w // 3, w // 3]:
            draw.ellipse([(cx + dx - 5, cy + h // 2 - 4), (cx + dx + 5, cy + h // 2 + 4)],
                          fill=(30, 30, 30), outline=(60, 60, 60))
        # Label
        label = self._short_label(elem)
        draw.text((cx - 30, cy + h // 2 + 8), label, fill=(220, 230, 240), font=font_small)
        # Confidence dot
        self._draw_confidence_dot(draw, cx + w // 2 + 4, cy - h // 2, elem.confidence)

    def _draw_person(self, draw, cx, cy, color, elem, font_label, font_small):
        r = 14
        # Shadow
        draw.ellipse([(cx - r + 2, cy - r + 2), (cx + r + 2, cy + r + 2)], fill=(0, 0, 0, 80))
        # Body circle
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)],
                      fill=color, outline=(255, 255, 255, 120), width=2)
        # Head
        draw.ellipse([(cx - 5, cy - r - 10), (cx + 5, cy - r)], fill=color, outline=(255, 255, 255, 80))
        # Label
        label = self._short_label(elem)
        draw.text((cx - 30, cy + r + 6), label, fill=(220, 230, 240), font=font_small)
        self._draw_confidence_dot(draw, cx + r + 4, cy - r, elem.confidence)

    def _draw_object(self, draw, cx, cy, color, elem, font_label, font_small):
        s = 12
        # Diamond shape
        points = [(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)]
        draw.polygon(points, fill=color, outline=(255, 255, 255, 120))
        label = self._short_label(elem)
        draw.text((cx - 30, cy + s + 6), label, fill=(220, 230, 240), font=font_small)
        self._draw_confidence_dot(draw, cx + s + 4, cy - s, elem.confidence)

    def _draw_confidence_dot(self, draw, x, y, confidence):
        if confidence > 0.7:
            c = (46, 213, 115)
        elif confidence > 0.4:
            c = (255, 200, 50)
        else:
            c = (255, 71, 87)
        draw.ellipse([(x, y), (x + 8, y + 8)], fill=c)

    @staticmethod
    def _short_label(elem: SceneElement) -> str:
        desc = elem.description or elem.type
        color_prefix = f"{elem.color} " if elem.color else ""
        text = f"{color_prefix}{desc}"
        return text[:28] + "…" if len(text) > 28 else text

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------

    def _draw_legend(
        self, draw: ImageDraw.Draw, elements: List[SceneElement],
        W: int, H: int,
        font_label: ImageFont.FreeTypeFont, font_small: ImageFont.FreeTypeFont,
    ):
        legend_y = H - 114
        draw.rectangle([(0, legend_y), (W, H)], fill=(12, 14, 20))
        draw.line([(0, legend_y), (W, legend_y)], fill=(0, 212, 255, 60), width=1)
        draw.text((14, legend_y + 6), "LEGEND", fill=(0, 212, 255), font=font_label)

        # Count types
        type_counts: Dict[str, int] = {}
        for e in elements:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1

        x_off = 14
        y_row = legend_y + 28
        for etype, count in type_counts.items():
            color = TYPE_COLORS.get(etype, (150, 150, 150))
            icon = TYPE_ICONS.get(etype, "■")
            draw.text((x_off, y_row), icon, fill=color, font=font_label)
            draw.text((x_off + 18, y_row), f"{etype.replace('_', ' ').title()} ({count})", fill=(180, 190, 200), font=font_small)
            x_off += 160

        # Confidence key
        y_conf = legend_y + 52
        draw.text((14, y_conf), "Confidence:", fill=(140, 150, 165), font=font_small)
        for i, (label, col) in enumerate([("High >70%", (46, 213, 115)), ("Med 40-70%", (255, 200, 50)), ("Low <40%", (255, 71, 87))]):
            bx = 110 + i * 130
            draw.ellipse([(bx, y_conf + 2), (bx + 10, y_conf + 12)], fill=col)
            draw.text((bx + 14, y_conf), label, fill=(160, 170, 180), font=font_small)

        # Element summary list
        y_list = legend_y + 74
        for i, elem in enumerate(elements[:6]):
            col = _resolve_color(elem)
            tx = 14 + (i % 3) * 330
            ty = y_list + (i // 3) * 18
            draw.rectangle([(tx, ty + 2), (tx + 10, ty + 12)], fill=col)
            draw.text((tx + 14, ty), f"{elem.description[:42]}", fill=(160, 170, 180), font=font_small)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> List[str]:
        words = text.split()
        lines: List[str] = []
        line = ""
        for w in words:
            if len(line) + len(w) + 1 > max_chars:
                lines.append(line.strip())
                line = w + " "
            else:
                line += w + " "
        if line.strip():
            lines.append(line.strip())
        return lines

    def health_check(self) -> bool:
        return self.client is not None


# Global instance
image_service = ImageGenerationService()
