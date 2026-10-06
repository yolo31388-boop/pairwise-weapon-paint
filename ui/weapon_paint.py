"""
武器涂装与自定义系统 - 核心模块

功能：
- 涂装应用：实际修改武器纹理、校验武器类型、支持多层叠加
- 图案编辑器：自定义图案、调整大小/位置/旋转
- 颜色选择器：自定义颜色、透明度、收藏并持久化
- 涂装保存：持久化到磁盘、槽位限制、分享码导入导出
- 涂装预览：实时渲染、考虑武器动作（换弹/开火）、3D 投影展示
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
import base64
import copy
import json
import math
import os


DEFAULT_BASE_COLOR = (64, 64, 64, 255)
DEFAULT_MAX_SLOTS = 8
DEFAULT_MAX_LAYERS = 8
DEFAULT_SAVE_PATH = "weapon_paint_saves.json"

# 武器动作对涂装图层施加的变换（随时间变化，模拟换弹/开火时涂装跟随武器运动）
ACTION_TRANSFORMS = {
    "idle": lambda t: (0.0, 0.0, 0.0),
    "reload": lambda t: (0.0, -0.25 * abs(math.sin(t * math.pi)), 0.0),
    "fire": lambda t: (-0.05 * math.sin(t * 20.0), 0.0, 8.0 * math.sin(t * 20.0)),
}


@dataclass
class Config:
    pass


@dataclass
class Color:
    r: int
    g: int
    b: int
    alpha: float = 1.0

    def to_dict(self) -> Dict:
        return {"r": self.r, "g": self.g, "b": self.b, "alpha": self.alpha}

    @staticmethod
    def from_dict(data: Dict) -> "Color":
        return Color(int(data["r"]), int(data["g"]), int(data["b"]), float(data.get("alpha", 1.0)))


@dataclass
class Pattern:
    """涂装图案：归一化坐标系 [-1, 1] 内的多边形，支持大小/位置/旋转。"""
    name: str
    points: List[Tuple[float, float]]
    size: float = 1.0
    position: Tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0  # 角度制

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "points": [list(p) for p in self.points],
            "size": self.size,
            "position": list(self.position),
            "rotation": self.rotation,
        }

    @staticmethod
    def from_dict(data: Dict) -> "Pattern":
        return Pattern(
            name=data["name"],
            points=[tuple(p) for p in data["points"]],
            size=float(data.get("size", 1.0)),
            position=tuple(data.get("position", (0.0, 0.0))),
            rotation=float(data.get("rotation", 0.0)),
        )


@dataclass
class PaintLayer:
    pattern: Pattern
    color: Color
    weapon_types: Optional[List[str]] = None  # None 表示适用于所有武器类型

    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern.to_dict(),
            "color": self.color.to_dict(),
            "weapon_types": self.weapon_types,
        }

    @staticmethod
    def from_dict(data: Dict) -> "PaintLayer":
        return PaintLayer(
            pattern=Pattern.from_dict(data["pattern"]),
            color=Color.from_dict(data["color"]),
            weapon_types=data.get("weapon_types"),
        )


class Texture:
    """武器纹理：width x height 的 RGBA 像素网格。"""

    def __init__(self, width: int = 32, height: int = 32,
                 base_color: Tuple[int, int, int, int] = DEFAULT_BASE_COLOR):
        self.width = width
        self.height = height
        self.pixels: List[List[List[int]]] = [
            [list(base_color) for _ in range(width)] for _ in range(height)
        ]

    def get_pixel(self, x: int, y: int) -> Tuple[int, int, int, int]:
        return tuple(self.pixels[y][x])

    def set_pixel(self, x: int, y: int, rgba: Sequence[int]) -> None:
        self.pixels[y][x] = [int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3])]

    def blend_pixel(self, x: int, y: int, color: Color) -> None:
        """按 alpha 将颜色混合到像素上。"""
        dst = self.pixels[y][x]
        src_a = max(0.0, min(1.0, color.alpha))
        dst_a = dst[3] / 255.0
        out_a = src_a + dst_a * (1.0 - src_a)
        if out_a <= 0.0:
            self.pixels[y][x] = [0, 0, 0, 0]
            return
        out = [
            int(round((color.r * src_a + dst[0] * dst_a * (1.0 - src_a)) / out_a)),
            int(round((color.g * src_a + dst[1] * dst_a * (1.0 - src_a)) / out_a)),
            int(round((color.b * src_a + dst[2] * dst_a * (1.0 - src_a)) / out_a)),
            int(round(out_a * 255)),
        ]
        self.pixels[y][x] = out

    def copy(self) -> "Texture":
        clone = Texture(self.width, self.height)
        clone.pixels = [[list(px) for px in row] for row in self.pixels]
        return clone


@dataclass
class Weapon:
    name: str
    weapon_type: str
    texture: Texture = field(default_factory=Texture)
    layers: List[PaintLayer] = field(default_factory=list)


@dataclass
class Preview:
    texture: Texture
    action: str
    view: str
    projection: List[Tuple[float, float]] = field(default_factory=list)  # 3D 投影的 2D 点


PRESET_PATTERNS: Dict[str, List[Tuple[float, float]]] = {
    "square": [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)],
    "triangle": [(0.0, -0.6), (0.6, 0.5), (-0.6, 0.5)],
    "stripe": [(-1.0, -0.15), (1.0, -0.15), (1.0, 0.15), (-1.0, 0.15)],
    "diamond": [(0.0, -0.6), (0.6, 0.0), (0.0, 0.6), (-0.6, 0.0)],
}


class WeaponPaint:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._state = {}
        self._history = []
        self._time = 0.0
        self.max_slots = int(self.config.get("max_slots", DEFAULT_MAX_SLOTS))
        self.max_layers = int(self.config.get("max_layers", DEFAULT_MAX_LAYERS))
        self.save_path = self.config.get("save_path", DEFAULT_SAVE_PATH)
        self._store = self._load_store()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def update(self, dt: float):
        self._time += dt

    def reset(self):
        self._state = {}
        self._history = []
        self._time = 0.0

    # ------------------------------------------------------------------
    # 图案编辑器
    # ------------------------------------------------------------------
    def create_pattern(self, name: str, points: Sequence[Sequence[float]]) -> Pattern:
        """创建自定义图案（归一化坐标多边形）。"""
        pts = [(float(p[0]), float(p[1])) for p in points]
        if len(pts) < 3:
            raise ValueError("自定义图案至少需要 3 个顶点")
        return Pattern(name=name, points=pts)

    def get_preset_pattern(self, name: str) -> Pattern:
        if name not in PRESET_PATTERNS:
            raise ValueError(f"未知预设图案: {name}")
        return Pattern(name=name, points=list(PRESET_PATTERNS[name]))

    def resize_pattern(self, pattern: Pattern, size: float) -> Pattern:
        if size <= 0:
            raise ValueError("图案大小必须为正数")
        pattern.size = float(size)
        return pattern

    def move_pattern(self, pattern: Pattern, x: float, y: float) -> Pattern:
        pattern.position = (float(x), float(y))
        return pattern

    def rotate_pattern(self, pattern: Pattern, degrees: float) -> Pattern:
        pattern.rotation = float(degrees) % 360.0
        return pattern

    # ------------------------------------------------------------------
    # 颜色选择器
    # ------------------------------------------------------------------
    def pick_color(self, r: int, g: int, b: int, alpha: float = 1.0) -> Color:
        """自定义颜色，支持透明度。"""
        for value in (r, g, b):
            if not 0 <= int(value) <= 255:
                raise ValueError("颜色分量必须在 0-255 之间")
        if not 0.0 <= float(alpha) <= 1.0:
            raise ValueError("透明度必须在 0.0-1.0 之间")
        return Color(int(r), int(g), int(b), float(alpha))

    def save_color(self, color: Color, name: Optional[str] = None) -> None:
        """收藏颜色并持久化，重启后仍可用。"""
        favorites = self._store.setdefault("colors", [])
        entry = color.to_dict()
        entry["name"] = name or f"color_{len(favorites)}"
        if not any(
            c["r"] == entry["r"] and c["g"] == entry["g"]
            and c["b"] == entry["b"] and c["alpha"] == entry["alpha"]
            for c in favorites
        ):
            favorites.append(entry)
            self._save_store()

    @property
    def favorite_colors(self) -> List[Color]:
        return [Color.from_dict(c) for c in self._store.get("colors", [])]

    # ------------------------------------------------------------------
    # 涂装应用
    # ------------------------------------------------------------------
    def create_weapon(self, name: str, weapon_type: str,
                      width: int = 32, height: int = 32) -> Weapon:
        return Weapon(name=name, weapon_type=weapon_type,
                      texture=Texture(width, height))

    def apply_paint(self, weapon: Weapon, layer: PaintLayer) -> int:
        """将涂装图层实际渲染到武器纹理上。返回图层索引。"""
        if layer.weapon_types is not None and weapon.weapon_type not in layer.weapon_types:
            raise ValueError(
                f"涂装不适用于武器类型 {weapon.weapon_type!r}，"
                f"仅支持: {layer.weapon_types}"
            )
        if len(weapon.layers) >= self.max_layers:
            raise ValueError(f"图层数量已达上限 {self.max_layers}")
        weapon.layers.append(layer)
        self._rasterize_layer(weapon.texture, layer)
        self._history.append(("apply", weapon.name, layer.pattern.name))
        return len(weapon.layers) - 1

    def _rasterize_layer(self, texture: Texture, layer: PaintLayer,
                         extra_offset: Tuple[float, float] = (0.0, 0.0),
                         extra_rotation: float = 0.0) -> None:
        pattern = layer.pattern
        rotation = math.radians(pattern.rotation + extra_rotation)
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        px = pattern.position[0] + extra_offset[0]
        py = pattern.position[1] + extra_offset[1]
        for y in range(texture.height):
            for x in range(texture.width):
                # 像素 -> 归一化坐标 [-1, 1]
                nx = (x + 0.5) / texture.width * 2.0 - 1.0
                ny = (y + 0.5) / texture.height * 2.0 - 1.0
                # 逆变换：平移 -> 旋转 -> 缩放
                dx, dy = nx - px, ny - py
                lx = (dx * cos_r + dy * sin_r) / pattern.size
                ly = (-dx * sin_r + dy * cos_r) / pattern.size
                if _point_in_polygon(lx, ly, pattern.points):
                    texture.blend_pixel(x, y, layer.color)

    # ------------------------------------------------------------------
    # 涂装保存 / 分享
    # ------------------------------------------------------------------
    def save_paint(self, slot: int, design: Sequence[PaintLayer]) -> None:
        """保存涂装方案到槽位并持久化到磁盘。"""
        self._check_slot(slot)
        slots = self._store.setdefault("slots", {})
        slots[str(slot)] = [layer.to_dict() for layer in design]
        self._save_store()

    def load_paint(self, slot: int) -> Optional[List[PaintLayer]]:
        self._check_slot(slot)
        data = self._store.get("slots", {}).get(str(slot))
        if data is None:
            return None
        return [PaintLayer.from_dict(d) for d in data]

    def delete_paint(self, slot: int) -> None:
        self._check_slot(slot)
        self._store.setdefault("slots", {}).pop(str(slot), None)
        self._save_store()

    def share_paint(self, slot: int) -> str:
        """导出槽位涂装为分享码。"""
        design = self._store.get("slots", {}).get(str(slot))
        if design is None:
            raise ValueError(f"槽位 {slot} 为空，无法分享")
        payload = json.dumps({"design": design}, ensure_ascii=False)
        return base64.b64encode(payload.encode("utf-8")).decode("ascii")

    def import_paint(self, share_code: str, slot: int) -> List[PaintLayer]:
        """导入分享码到指定槽位。"""
        self._check_slot(slot)
        try:
            payload = json.loads(base64.b64decode(share_code).decode("utf-8"))
            design = [PaintLayer.from_dict(d) for d in payload["design"]]
        except Exception as exc:
            raise ValueError("无效的涂装分享码") from exc
        self.save_paint(slot, design)
        return design

    def _check_slot(self, slot: int) -> None:
        if not 0 <= int(slot) < self.max_slots:
            raise ValueError(f"槽位 {slot} 超出限制（共 {self.max_slots} 个槽位）")

    def _load_store(self) -> Dict:
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_store(self) -> None:
        with open(self.save_path, "w", encoding="utf-8") as fh:
            json.dump(self._store, fh, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 涂装预览
    # ------------------------------------------------------------------
    def paint_preview(self, weapon: Weapon,
                      layers: Optional[Sequence[PaintLayer]] = None,
                      action: str = "idle", view: str = "3d") -> Preview:
        """渲染涂装预览：应用图层、模拟武器动作、可选 3D 投影。"""
        if action not in ACTION_TRANSFORMS:
            raise ValueError(f"未知武器动作: {action}")
        texture = weapon.texture.copy()
        offset_x, offset_y, extra_rot = ACTION_TRANSFORMS[action](self._time)
        for layer in list(weapon.layers) + list(layers or []):
            if layer.weapon_types is not None and weapon.weapon_type not in layer.weapon_types:
                continue
            self._rasterize_layer(texture, layer, (offset_x, offset_y), extra_rot)
        projection: List[Tuple[float, float]] = []
        if view == "3d":
            projection = self._project_3d()
        elif view != "2d":
            raise ValueError(f"未知预览视图: {view}")
        return Preview(texture=texture, action=action, view=view, projection=projection)

    def _project_3d(self) -> List[Tuple[float, float]]:
        """将武器简化为单位立方体，绕 Y 轴随时间旋转后做透视投影。"""
        angle = self._time
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        distance = 3.0
        points = []
        for x in (-1.0, 1.0):
            for y in (-1.0, 1.0):
                for z in (-1.0, 1.0):
                    rx = x * cos_a - z * sin_a
                    rz = x * sin_a + z * cos_a
                    scale = distance / (distance + rz)
                    points.append((rx * scale, y * scale))
        return points


def _point_in_polygon(x: float, y: float, points: Sequence[Tuple[float, float]]) -> bool:
    """射线法判断点是否在多边形内。"""
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside
