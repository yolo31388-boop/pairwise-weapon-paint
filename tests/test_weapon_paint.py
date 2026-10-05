"""
武器涂装与自定义系统 - 验收测试
运行方式：python -m pytest tests/test_weapon_paint.py -q
共 14 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.weapon_paint import WeaponPaint, PaintLayer


def make_layer(system, pattern_name="square", color=(255, 0, 0), weapon_types=None):
    pattern = system.get_preset_pattern(pattern_name)
    return PaintLayer(pattern=pattern, color=system.pick_color(*color), weapon_types=weapon_types)


class TestWeaponPaint:
    def setup_method(self):
        self.system = WeaponPaint()

    # 1. 涂装应用实际修改武器纹理，而不是只设标志位
    def test_case_01(self):
        weapon = self.system.create_weapon("AK-47", "rifle")
        before = weapon.texture.get_pixel(16, 16)
        self.system.apply_paint(weapon, make_layer(self.system))
        after = weapon.texture.get_pixel(16, 16)
        assert after != before
        assert after[:3] == (255, 0, 0)

    # 2. 涂装检查武器类型，不兼容时拒绝
    def test_case_02(self):
        weapon = self.system.create_weapon("AWP", "sniper")
        layer = make_layer(self.system, weapon_types=["rifle"])
        with pytest.raises(ValueError):
            self.system.apply_paint(weapon, layer)
        assert len(weapon.layers) == 0
        ok_layer = make_layer(self.system, weapon_types=["sniper", "rifle"])
        self.system.apply_paint(weapon, ok_layer)
        assert len(weapon.layers) == 1

    # 3. 涂装支持多层叠加
    def test_case_03(self):
        weapon = self.system.create_weapon("M4A1", "rifle")
        red = make_layer(self.system, "square", (255, 0, 0))
        blue = make_layer(self.system, "square", (0, 0, 255))
        blue.pattern.size = 0.5
        self.system.apply_paint(weapon, red)
        self.system.apply_paint(weapon, blue)
        assert len(weapon.layers) == 2
        assert weapon.texture.get_pixel(16, 16)[:3] == (0, 0, 255)
        assert weapon.texture.get_pixel(9, 9)[:3] == (255, 0, 0)

    # 4. 图案编辑器支持自定义图案
    def test_case_04(self):
        pattern = self.system.create_pattern(
            "my_star", [(0, -0.8), (0.2, -0.2), (0.8, 0), (0.2, 0.2), (0, 0.8), (-0.2, 0.2), (-0.8, 0), (-0.2, -0.2)]
        )
        assert pattern.name == "my_star"
        assert len(pattern.points) == 8
        weapon = self.system.create_weapon("USP", "pistol")
        layer = PaintLayer(pattern=pattern, color=self.system.pick_color(0, 255, 0))
        self.system.apply_paint(weapon, layer)
        assert weapon.texture.get_pixel(16, 16)[:3] == (0, 255, 0)

    # 5. 图案可以调整大小
    def test_case_05(self):
        weapon = self.system.create_weapon("AK-47", "rifle")
        pattern = self.system.get_preset_pattern("square")
        self.system.resize_pattern(pattern, 0.2)
        assert pattern.size == 0.2
        layer = PaintLayer(pattern=pattern, color=self.system.pick_color(255, 0, 0))
        self.system.apply_paint(weapon, layer)
        assert weapon.texture.get_pixel(16, 16)[:3] == (255, 0, 0)
        assert weapon.texture.get_pixel(2, 2)[:3] != (255, 0, 0)
        with pytest.raises(ValueError):
            self.system.resize_pattern(pattern, 0)

    # 6. 图案可以调整位置
    def test_case_06(self):
        weapon = self.system.create_weapon("AK-47", "rifle")
        pattern = self.system.get_preset_pattern("square")
        self.system.move_pattern(pattern, 0.6, 0.0)
        assert pattern.position == (0.6, 0.0)
        layer = PaintLayer(pattern=pattern, color=self.system.pick_color(255, 0, 0))
        self.system.apply_paint(weapon, layer)
        assert weapon.texture.get_pixel(28, 16)[:3] == (255, 0, 0)
        assert weapon.texture.get_pixel(4, 16)[:3] != (255, 0, 0)

    # 7. 图案可以旋转
    def test_case_07(self):
        weapon = self.system.create_weapon("AK-47", "rifle")
        pattern = self.system.get_preset_pattern("stripe")
        self.system.rotate_pattern(pattern, 90)
        assert pattern.rotation == 90
        layer = PaintLayer(pattern=pattern, color=self.system.pick_color(255, 0, 0))
        self.system.apply_paint(weapon, layer)
        # 横条纹旋转 90 度后变为竖条纹：中心列被涂，两侧行不被涂
        assert weapon.texture.get_pixel(16, 2)[:3] == (255, 0, 0)
        assert weapon.texture.get_pixel(2, 16)[:3] != (255, 0, 0)

    # 8. 颜色选择器支持自定义颜色
    def test_case_08(self):
        color = self.system.pick_color(12, 34, 56)
        assert (color.r, color.g, color.b) == (12, 34, 56)
        with pytest.raises(ValueError):
            self.system.pick_color(300, 0, 0)
        weapon = self.system.create_weapon("Glock", "pistol")
        layer = PaintLayer(pattern=self.system.get_preset_pattern("square"), color=color)
        self.system.apply_paint(weapon, layer)
        assert weapon.texture.get_pixel(16, 16)[:3] == (12, 34, 56)

    # 9. 颜色支持透明度调整
    def test_case_09(self):
        weapon = self.system.create_weapon("AK-47", "rifle")
        base = weapon.texture.get_pixel(16, 16)
        half_red = self.system.pick_color(255, 0, 0, alpha=0.5)
        layer = PaintLayer(pattern=self.system.get_preset_pattern("square"), color=half_red)
        self.system.apply_paint(weapon, layer)
        blended = weapon.texture.get_pixel(16, 16)
        assert base[0] < blended[0] < 255
        with pytest.raises(ValueError):
            self.system.pick_color(0, 0, 0, alpha=1.5)

    # 10. 收藏的颜色持久化保存，重启后仍在
    def test_case_10(self, tmp_path):
        save_file = str(tmp_path / "saves.json")
        sys1 = WeaponPaint({"save_path": save_file})
        sys1.save_color(sys1.pick_color(1, 2, 3, alpha=0.7), name="我的颜色")
        sys2 = WeaponPaint({"save_path": save_file})
        favorites = sys2.favorite_colors
        assert len(favorites) == 1
        assert (favorites[0].r, favorites[0].g, favorites[0].b) == (1, 2, 3)
        assert favorites[0].alpha == pytest.approx(0.7)

    # 11. 涂装保存持久化，重启游戏后不丢失
    def test_case_11(self, tmp_path):
        save_file = str(tmp_path / "saves.json")
        sys1 = WeaponPaint({"save_path": save_file})
        design = [make_layer(sys1, "diamond", (10, 20, 30), weapon_types=["rifle"])]
        sys1.save_paint(0, design)
        sys2 = WeaponPaint({"save_path": save_file})
        loaded = sys2.load_paint(0)
        assert loaded is not None
        assert loaded[0].pattern.name == "diamond"
        assert (loaded[0].color.r, loaded[0].color.g, loaded[0].color.b) == (10, 20, 30)
        assert loaded[0].weapon_types == ["rifle"]

    # 12. 保存有槽位限制，不能无限保存
    def test_case_12(self, tmp_path):
        save_file = str(tmp_path / "saves.json")
        system = WeaponPaint({"save_path": save_file, "max_slots": 2})
        design = [make_layer(system)]
        system.save_paint(0, design)
        system.save_paint(1, design)
        with pytest.raises(ValueError):
            system.save_paint(2, design)
        with pytest.raises(ValueError):
            system.load_paint(5)

    # 13. 涂装支持分享码导出与导入
    def test_case_13(self, tmp_path):
        sys1 = WeaponPaint({"save_path": str(tmp_path / "a.json")})
        sys2 = WeaponPaint({"save_path": str(tmp_path / "b.json")})
        design = [make_layer(sys1, "triangle", (200, 100, 50))]
        sys1.save_paint(0, design)
        code = sys1.share_paint(0)
        imported = sys2.import_paint(code, 1)
        assert imported[0].pattern.name == "triangle"
        assert (imported[0].color.r, imported[0].color.g, imported[0].color.b) == (200, 100, 50)
        assert sys2.load_paint(1)[0].pattern.name == "triangle"
        with pytest.raises(ValueError):
            sys2.import_paint("!!!invalid!!!", 0)

    # 14. 涂装预览实际生效、考虑武器动作且有 3D 展示
    def test_case_14(self):
        weapon = self.system.create_weapon("AK-47", "rifle")
        layer = make_layer(self.system, "square", (255, 0, 0))
        preview = self.system.paint_preview(weapon, layers=[layer], view="3d")
        # 预览实际渲染了涂装，但不影响原武器纹理
        assert preview.texture.get_pixel(16, 16)[:3] == (255, 0, 0)
        assert weapon.texture.get_pixel(16, 16)[:3] != (255, 0, 0)
        # 3D 展示：立方体投影出 8 个顶点
        assert len(preview.projection) == 8
        # 武器动作：开火时涂装随时间移动
        p1 = self.system.paint_preview(weapon, layers=[layer], action="fire", view="2d")
        self.system.update(0.05)
        p2 = self.system.paint_preview(weapon, layers=[layer], action="fire", view="2d")
        assert p1.texture.pixels != p2.texture.pixels
        with pytest.raises(ValueError):
            self.system.paint_preview(weapon, action="dance")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
