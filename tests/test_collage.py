from dataclasses import replace

from PIL import Image

from mangosteen.imaging import compose
from mangosteen.imaging.compose import RGBA, CollageBackground, CollageLayout, CollageSettings

RED, BLUE = (220, 30, 30), (30, 30, 220)
BASE = CollageSettings(layout=CollageLayout.ROW, width=800, spacing=0.05, format=compose.FileFormat.PNG)


def photos():
    return [Image.new("RGB", (400, 300), RED), Image.new("RGB", (400, 300), BLUE)]


def test_gradient_background_is_the_background_tools_gradient():
    settings = replace(BASE, background_style=CollageBackground.GRADIENT)
    assert (settings.gradient_start, settings.gradient_end, settings.gradient_angle) == (
        compose.FrameSettings().gradient_start, compose.FrameSettings().gradient_end, 135.0)
    result = compose.compose_collage(photos(), settings)
    expected = compose._gradient(result.size, settings.gradient_start, settings.gradient_end, 135.0)
    for point in [(2, 2), (result.width - 3, result.height - 3), (result.width // 2, 3)]:  # in the margin
        assert result.getpixel(point) == expected.getpixel(point)
    # 135°: the start colour is at the bottom right, the end colour at the top left.
    assert result.getpixel((result.width - 1, result.height - 1))[0] > result.getpixel((0, 0))[0]


def test_colour_background_stays_a_colour():
    result = compose.compose_collage(photos(), replace(BASE, background=RGBA(0, 1, 0)))
    assert result.getpixel((2, 2))[:3] == (0, 255, 0)


def test_no_shadow_by_default():
    assert CollageSettings().shadow == 0
    result = compose.compose_collage(photos(), BASE)
    width, height, cells = compose.collage_layout([4 / 3, 4 / 3], BASE)
    x, y, w, h = cells[0]
    assert result.getpixel((round(x + w / 2), round(y + h) + 3))[:3] == (255, 255, 255)


def test_shadow_falls_below_each_cell_and_not_on_the_neighbour():
    settings = replace(BASE, shadow=1.0, spacing=0.06)
    result = compose.compose_collage(photos(), settings)
    _width, _height, cells = compose.collage_layout([4 / 3, 4 / 3], settings)
    for x, y, w, h in cells:
        below = result.getpixel((round(x + w / 2), round(y + h) + 4))
        above = result.getpixel((round(x + w / 2), round(y) - 4))
        assert below[0] < 250 and below[0] < above[0]  # darker, and more below than above (it is moved down)
    # Photos are drawn after every shadow: the second photo next to the first keeps its own colour.
    x, y, w, h = cells[1]
    assert result.getpixel((round(x) + 2, round(y + h / 2)))[:3] == BLUE
    x, y, w, h = cells[0]
    assert result.getpixel((round(x + w) - 2, round(y + h / 2)))[:3] == RED


def test_shadow_strength_grows_with_the_slider():
    def darkness(shadow):
        settings = replace(BASE, shadow=shadow, spacing=0.06)
        result = compose.compose_collage(photos(), settings)
        x, y, w, h = compose.collage_layout([4 / 3, 4 / 3], settings)[2][0]
        return 255 - result.getpixel((round(x + w / 2), round(y + h) + 6))[0]

    assert 0 < darkness(0.3) < darkness(1.0)


def test_moving_a_photo_in_the_preview_shifts_the_others(qapp, tmp_path):
    from mangosteen.ui.tools.collage_tool import CollageTool

    paths = []
    for index in range(4):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (40, 30), (index * 60, 0, 0)).save(path)
        paths.append(str(path))

    class Context:
        settings = None
        jobs = None

    tool = CollageTool(paths, Context())
    tool._rendered_order = list(paths)
    tool._moved_in_preview(0, 2)
    assert tool.order == [paths[1], paths[2], paths[0], paths[3]]
    assert [tool._list.item(i).data(256) for i in range(tool._list.count())] == tool.order
    tool._rendered_order = list(tool.order)
    tool._moved_in_preview(3, 0)
    assert tool.order == [paths[3], paths[1], paths[2], paths[0]]
    tool.close()
