import logging
import base64
import math
import hashlib
import random
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
        # Try Imagen AI generation first
        try:
            from app.services.imagen_service import imagen_service

            imagen_bytes = await imagen_service.generate_scene(scene_description)
            if imagen_bytes:
                logger.info("Generated scene image via Imagen AI")
                return imagen_bytes
        except Exception as e:
            logger.warning(f"Imagen generation failed, falling back to PIL: {e}")

        # Fallback to PIL diagram
        try:
            image = self._create_scene_diagram(scene_description, elements)
            buf = BytesIO()
            image.save(buf, format="PNG")
            logger.info("Generated scene diagram image (PIL fallback)")
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

        # --- dynamic 3D-style environment backdrop ---
        self._draw_road_grid(draw, W, H, scene_description)

        # --- header bar ---
        draw.rectangle([(0, 0), (W, 50)], fill=(12, 14, 20))
        draw.text((14, 14), "🔍 3D SCENE RECONSTRUCTION", fill=(0, 212, 255), font=font_title)
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

    def _draw_road_grid(self, draw: ImageDraw.Draw, W: int, H: int, scene_description: str = ""):
        """Draw a dynamic 3D-style environment without fixed scene templates."""
        # Sky gradient
        sky_top = (14, 20, 34)
        sky_bottom = (36, 60, 94)
        horizon = int(H * 0.34)
        for y in range(0, horizon):
            t = y / max(horizon, 1)
            color = (
                int(sky_top[0] + (sky_bottom[0] - sky_top[0]) * t),
                int(sky_top[1] + (sky_bottom[1] - sky_top[1]) * t),
                int(sky_top[2] + (sky_bottom[2] - sky_top[2]) * t),
            )
            draw.line([(0, y), (W, y)], fill=color, width=1)

        # Ground gradient
        ground_top = (56, 60, 66)
        ground_bottom = (34, 38, 44)
        for y in range(horizon, H):
            t = (y - horizon) / max(H - horizon, 1)
            color = (
                int(ground_top[0] + (ground_bottom[0] - ground_top[0]) * t),
                int(ground_top[1] + (ground_bottom[1] - ground_top[1]) * t),
                int(ground_top[2] + (ground_bottom[2] - ground_top[2]) * t),
            )
            draw.line([(0, y), (W, y)], fill=color, width=1)

        desc = (scene_description or "").lower().strip()
        seed_src = desc or "scene-default"
        seed = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Perspective guide lines (vary by description so each scene is unique)
        vanishing_x = int(W * (0.38 + 0.24 * rng.random()))
        if "left" in desc:
            vanishing_x = int(W * (0.32 + 0.08 * rng.random()))
        elif "right" in desc:
            vanishing_x = int(W * (0.60 + 0.08 * rng.random()))

        guide_spacing = int(90 + rng.random() * 45)
        for x in range(-W // 2, W + W // 2, guide_spacing):
            draw.line([(x, H), (vanishing_x, horizon)], fill=(62, 68, 76), width=1)

        depth_rows = 10 + int(rng.random() * 4)
        for i in range(1, depth_rows):
            t = i / depth_rows
            y = H - int((t ** 1.6) * (H - horizon))
            draw.line([(0, y), (W, y)], fill=(64, 70, 78), width=1)

        # Main road only when testimony suggests one
        has_road = any(k in desc for k in ["street", "road", "lane", "highway", "avenue", "boulevard"])
        road_center = vanishing_x
        if has_road:
            road_center += int((rng.random() - 0.5) * W * 0.16)
            road_center = max(int(W * 0.2), min(int(W * 0.8), road_center))
            near_half = int(W * (0.20 + rng.random() * 0.10))
            far_half = int(W * (0.04 + rng.random() * 0.04))
            road_top_y = horizon + int(10 + rng.random() * 20)
            road_poly = [
                (road_center - near_half, H),
                (road_center + near_half, H),
                (road_center + far_half, road_top_y),
                (road_center - far_half, road_top_y),
            ]
            draw.polygon(road_poly, fill=(48, 52, 58))
            for i in range(1, 11):
                t = i / 11
                y = H - int((t ** 1.45) * (H - (road_top_y + 6)))
                w = int(near_half - (near_half - far_half) * t)
                if i % 2 == 0:
                    draw.rectangle(
                        [(road_center - 2, y - 7), (road_center + 2, y + 3)],
                        fill=(220, 210, 120),
                    )
                draw.line([(road_center - w, y), (road_center + w, y)], fill=(64, 68, 74), width=1)

        # Optional intersecting lane rendered with scene-specific angle (no fixed cross template)
        if any(k in desc for k in ["intersection", "junction", "crosswalk", "crossing"]):
            cross_y = int(H * (0.50 + rng.random() * 0.14))
            near_half = int(W * (0.28 + rng.random() * 0.08))
            far_half = int(W * (0.08 + rng.random() * 0.05))
            tilt = int(W * (0.08 + rng.random() * 0.12))
            cross_poly = [
                (-near_half, cross_y + 42),
                (W + near_half, cross_y - 28),
                (W + far_half + tilt, cross_y - 78),
                (-far_half + tilt, cross_y - 8),
            ]
            draw.polygon(cross_poly, fill=(50, 54, 60))

            # Crosswalk stripes follow angled lane
            for i in range(9):
                offset = i * 52 - 30
                x1 = offset
                y1 = cross_y + 24 - int(offset * 0.14)
                x2 = x1 + 22
                y2 = y1 - 8
                draw.polygon(
                    [(x1, y1), (x2, y2), (x2 + 4, y2 - 6), (x1 + 4, y1 - 6)],
                    fill=(210, 210, 210),
                )

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
        w, h = 62, 28
        # Determine if truck/large
        desc_l = (elem.description or "").lower() + (elem.size or "").lower()
        if any(k in desc_l for k in ["truck", "suv", "van", "bus", "large"]):
            w, h = 78, 34

        depth = max(8, h // 3)
        # Soft shadow
        draw.ellipse([(cx - w // 2, cy + h // 2 + 4), (cx + w // 2, cy + h // 2 + 14)], fill=(22, 24, 30))

        # Isometric top
        top = [
            (cx - w // 2, cy - h // 2),
            (cx + w // 2, cy - h // 2),
            (cx + w // 2 + depth, cy - h // 2 - depth),
            (cx - w // 2 + depth, cy - h // 2 - depth),
        ]
        right_face = [
            (cx + w // 2, cy - h // 2),
            (cx + w // 2, cy + h // 2),
            (cx + w // 2 + depth, cy + h // 2 - depth),
            (cx + w // 2 + depth, cy - h // 2 - depth),
        ]
        front_face = [
            (cx - w // 2, cy + h // 2),
            (cx + w // 2, cy + h // 2),
            (cx + w // 2 + depth, cy + h // 2 - depth),
            (cx - w // 2 + depth, cy + h // 2 - depth),
        ]

        draw.polygon(top, fill=tuple(min(255, c + 26) for c in color), outline=(235, 238, 245))
        draw.polygon(right_face, fill=tuple(max(0, c - 30) for c in color), outline=(220, 224, 232))
        draw.polygon(front_face, fill=color, outline=(220, 224, 232))

        # Windshield highlight
        wx1 = cx - w // 5 + depth // 2
        wx2 = cx + w // 6 + depth // 2
        wy1 = cy - h // 2 - depth + 2
        wy2 = wy1 + 6
        draw.polygon([(wx1, wy2), (wx2, wy2), (wx2 + 6, wy1), (wx1 + 6, wy1)], fill=(175, 205, 232))
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
        r = 11
        # Shadow
        draw.ellipse([(cx - r - 4, cy + r + 6), (cx + r + 4, cy + r + 14)], fill=(22, 24, 30))
        # Torso (capsule-like)
        body_color = tuple(max(0, c - 8) for c in color)
        draw.rounded_rectangle([(cx - r, cy - r), (cx + r, cy + r + 8)], radius=7,
                               fill=body_color, outline=(235, 235, 240), width=1)
        # Head
        draw.ellipse([(cx - 6, cy - r - 12), (cx + 6, cy - r)], fill=tuple(min(255, c + 10) for c in color),
                     outline=(235, 235, 240))
        # Label
        label = self._short_label(elem)
        draw.text((cx - 30, cy + r + 14), label, fill=(220, 230, 240), font=font_small)
        self._draw_confidence_dot(draw, cx + r + 4, cy - r, elem.confidence)

    def _draw_object(self, draw, cx, cy, color, elem, font_label, font_small):
        s = 12
        # Isometric cube-like marker
        top = [(cx, cy - s), (cx + s, cy - s // 2), (cx, cy), (cx - s, cy - s // 2)]
        right = [(cx + s, cy - s // 2), (cx + s, cy + s // 2), (cx, cy + s), (cx, cy)]
        left = [(cx - s, cy - s // 2), (cx, cy), (cx, cy + s), (cx - s, cy + s // 2)]
        draw.polygon(top, fill=tuple(min(255, c + 18) for c in color), outline=(235, 235, 240))
        draw.polygon(right, fill=tuple(max(0, c - 22) for c in color), outline=(215, 215, 225))
        draw.polygon(left, fill=color, outline=(215, 215, 225))
        draw.ellipse([(cx - s, cy + s + 4), (cx + s, cy + s + 12)], fill=(22, 24, 30))
        label = self._short_label(elem)
        draw.text((cx - 30, cy + s + 10), label, fill=(220, 230, 240), font=font_small)
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
