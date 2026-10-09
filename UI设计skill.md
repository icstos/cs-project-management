# UI 设计 skill —— 适配 Flet 程序的界面美化指南

> 这份文档记录"把一套能用的 Flet 界面，改造成现代、耐看、深浅色都能用的界面"的
> 完整方法与踩坑经验。所有结论都在 **flet 1.0.4 + Windows 桌面端**上实测过，
> 配套实现见本仓库 `view/design.py`、`view/widgets.py` 与四个页面模块。

---

## 0. 一句话方法论

**把"视觉决策"从代码里抽出来，收敛成一层令牌，再让所有组件只消费令牌。**

界面之所以"看起来不专业"，几乎从来不是因为某个控件不够花哨，而是因为：
间距各处不同、圆角各写各的、字号没有层级、颜色随手取近似值。
把这几件事收敛到一个模块（`view/design.py`），一致性就自动成立了。

三条纪律：

1. **不写魔法数字。** 组件里出现 `padding=13`、`radius=11` 这类值时，先问它该属于哪一级令牌。
2. **不写死色值。** 组件只说"意图"（成功 / 警告 / 主色 / 次级信息），色值由色板翻译。
3. **不重复造组件。** 按钮、卡片、标签、空状态、加载态统一从 `view/widgets.py` 出。

---

## 1. 设计令牌：先定标尺，再画界面

### 1.1 间距：8 的倍数 + 12 列栅格

```python
SPACE_XXS = 2;  SPACE_XS = 4;  SPACE_SM = 8;   SPACE_MD = 12
SPACE_LG  = 16; SPACE_XL = 24; SPACE_XXL = 32; SPACE_3XL = 40

PAGE_PADDING    = SPACE_XL   # 页面边距 24
SECTION_SPACING = SPACE_XL   # 模块间距 24
GRID_GUTTER     = SPACE_LG   # 卡片栅格 16
CARD_PADDING    = SPACE_LG   # 卡片内边距 16
FIELD_GAP       = SPACE_MD   # 表单字段 12
```

* 页面边距优先取 **24**，它给窗口边缘留出的呼吸感最接近"现代桌面应用"。
* 卡片之间留 **16**，模块之间留 **24**：同级用同一档，跨级换档，层级感来自间距而不是线条。
* 栅格用 `ft.ResponsiveRow` + `col={"xs": 12, "md": 6, "xl": 4}`——
  **永远不要用固定像素宽去拼多列**，窗口一缩就散架。

> ⚠️ `Row(wrap=True)` 的子项**不能**带 `expand`；需要撑开的元素放在不换行的行里。

### 1.2 圆角：按控件类型分档，不要统一

| 用途 | 令牌 | 值 |
| --- | --- | --- |
| 输入框 / 选择器 | `RADIUS_INPUT` | 8 |
| 按钮 | `RADIUS_BUTTON` | 10 |
| 卡片 / 面板 | `RADIUS_CARD` | 14 |
| 对话框 | `RADIUS_DIALOG` | 18 |
| 标签 / 胶囊 | `RADIUS_PILL` | 999 |

同一档内的控件圆角必须一致；跨档要有明显肉眼可辨的差别，否则"不一致"和"没对齐"看起来是同一回事。

### 1.3 五级字体层级

| 层级 | 字号 | 字重 | 行高 | 用途 |
| --- | --- | --- | --- | --- |
| `DISPLAY` | 22 | 600 | 1.30 | 页面大标题 |
| `TITLE` | 15 | 600 | 1.40 | 卡片 / 区块小标题 |
| `BODY` | 13 | 400 | 1.55 | 正文 |
| `LABEL` | 12 | 500 | 1.45 | 辅助文字、行内次要信息 |
| `CAPTION` | 11 | 400 | 1.40 | 说明文字、路径、快捷键 |

* **正文行高 1.5-1.6**：中英混排时明显更透气。
* **标题字重 500-600**，不要用 700+：粗黑体在 13-15px 时显脏。
* 所有文本都必须走一个工厂函数，字号 / 字重 / 行高 / 字距由层级决定，
  避免"某处 12px、某处 13px"的漂移：

```python
def text(value, *, level=TextLevel.BODY, color=None, weight=None, size=None, **kw):
    base = LEVELS[level]
    return ft.Text(
        value,
        size=size or base.size,
        weight=weight or base.weight,
        color=color or ft.Colors.ON_SURFACE,   # ← 见下方踩坑 #2，必须兜底
        font_family=FONT_FAMILY,
        style=ft.TextStyle(height=base.height, letter_spacing=base.spacing),
        **kw,
    )
```

### 1.4 配色：主色 + 辅助色 + 中性色

* **主色**选**低饱和**色系（本项目：`#4356C7` 靛蓝）。高饱和主色在整屏大面积使用时非常刺眼。
* **中性色**用带一点点冷调的灰（`#F5F6F9 / #E3E6EE / #5C6373 / #1A1C22`），比纯灰"干净"。
* **文字对比度按 WCAG AA（≥4.5:1）挑**：正文 `#1A1C22 on #F5F6F9` 约 15:1，
  次级文字 `#5C6373 on #FFFFFF` 约 6:1，都安全。
* 语义色（成功 / 警告 / 危险 / 信息）**每个都配三档**：`accent`（图标与强调）、
  `container`（浅底）、`on_container`（落在浅底上的文字），三者成对使用才不会翻车。

```python
@dataclass(frozen=True, slots=True)
class ToneStyle:
    accent: ft.ColorValue        # 图标 / 强调文字
    container: ft.ColorValue     # 胶囊底色、指标图标底色
    on_container: ft.ColorValue  # 落在 container 上的文字
```

### 1.5 深浅双模式：一套代码 + 两张色板

**不要为深色模式写第二套界面代码。** 做法是：

1. 组件只引用**语义角色**：`ft.Colors.SURFACE`、`ft.Colors.ON_SURFACE_VARIANT`、
   `ft.Colors.OUTLINE_VARIANT`……
2. 客户端按当前亮度把角色解析成具体色值；
3. 入口同时注册两套 `ft.Theme`：

```python
page.theme       = design.build_theme()        # 浅色
page.dark_theme  = design.build_dark_theme()   # 深色（结构完全相同，只有色板不同）
page.theme_mode  = ft.ThemeMode.LIGHT
```

4. 切换只需改 `page.theme_mode`。

```python
def toggle_theme(_=None):
    next_dark = not dark
    T.set_dark(next_dark)                        # ① 同步 Python 侧色板
    page.theme_mode = ft.ThemeMode.DARK if next_dark else ft.ThemeMode.LIGHT
    set_dark_state(next_dark)                    # ② 触发一次重渲染
```

> **为什么需要 `set_dark()`？** 客户端能自己解析 `ft.Colors.*`，但 Python 侧还有查表
> 逻辑（语义色、阴影深浅、git 增删色）。这些必须在每次渲染前同步，否则会出现
> "半深半浅"。做法是在外壳组件渲染的第一行调用 `T.set_dark(dark)`。

### 1.6 阴影：极淡、向下、分三档

```python
card_shadow()        # 静止：offset(0,3) blur 12 opacity 0.05
card_shadow(hover=1) # 悬停：offset(0,6) blur 20 opacity 0.10
floating_shadow()    # 浮层：offset(0,12) blur 32 opacity 0.16
```

* 浅色下阴影 **不要超过 12% 不透明度**，否则立刻变"廉价感"。
* 深色下阴影几乎不可见，靠**表面层级**（surface / surface_container_low / high）拉开层次。
* 卡片阴影用"极淡"档，配上**1px 发丝边框**（`OUTLINE_VARIANT`）就有了细腻质感。

### 1.7 动效：150-300ms，ease-out，只给关键操作

```python
DURATION_FAST = 150   # 悬停 / 图标按钮
DURATION_BASE = 200   # 卡片、按钮
DURATION_SLOW = 280   # 面板展开

ft.Container(animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT), ...)
```

* Flutter 的 `Container.animate` 会生成 `AnimatedContainer`，属性变化自动补间。
* **不要给会随窗口尺寸变化的东西加动画**（例如带显式 width 的容器），否则拉窗口时会橡皮筋。
  `expand` 出来的尺寸不会触发动画，可以放心用。
* 动效只放在：悬停抬升、状态徽标切换、加载→完成。页面切换不做花哨转场。

---

## 2. 组件规范

### 2.1 按钮：三态齐备

```python
ft.ButtonStyle(
    shape=ft.RoundedRectangleBorder(radius=RADIUS_BUTTON),   # 8-12
    padding=ft.Padding.symmetric(horizontal=18, vertical=12),
    elevation={DEFAULT: 0, HOVERED: 1, PRESSED: 0, DISABLED: 0},   # 悬停"轻微浮起"
    shadow_color=with_opacity(0.22, "#0B0E14"),
    overlay_color=with_opacity(0.12, ON_PRIMARY),                  # 按下反馈
    animation_duration=ft.Duration(milliseconds=200),
    mouse_cursor=ft.MouseCursor.CLICK,
)
```

* **主按钮**实色填充；**次按钮**描边（悬停时边框与文字一起转主色）；**文字按钮**最轻。
* 危险操作单独一档（`ERROR` 填充），且只出现在"删除 / 移除"这类不可逆动作上。
* 禁用态：`bgcolor=with_opacity(0.12, ON_SURFACE)`、`color=with_opacity(0.38, ON_SURFACE)`，
  让它"灰下去"而不是"消失"。

### 2.2 卡片

```python
ft.Container(
    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,   # 浅色=白，深色=比页面亮一档
    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
    border_radius=RADIUS_CARD,                 # 12-16
    shadow=card_shadow(),
    animate=ft.Animation(200, EASE_OUT),
)
```

* **悬停阴影加深**必须靠"状态重渲染"实现（见踩坑 #1），不能直接改控件属性。
* 卡片内部用 `spacing=12/16` 分块，区块之间可以用一条 `Divider` 收尾，
  但不要每块都加边框——**层级靠间距，不靠线**。

### 2.3 输入框 / 选择器

```python
ft.TextField(
    border=design.field_border(),        # ⚠️ 不是 border_radius（1.0 已废弃）
    filled=True,
    fill_color=with_opacity(0.045, ft.Colors.ON_SURFACE),  # 注意是 ColorValue，不是状态字典
    dense=True,
)
```

```python
def field_border(radius=RADIUS_INPUT):
    return {
        FOCUSED: ft.OutlineInputBorder(border_radius=radius, side=ft.BorderSide(2, PRIMARY)),
        DEFAULT: ft.OutlineInputBorder(border_radius=radius, side=ft.BorderSide(1, OUTLINE_VARIANT)),
    }
```

* 默认 1px 发丝线 → 聚焦 2px 主色，反馈明确且不需要额外阴影。
* 表单错误用 `inline_error()` 显示在字段下方：**红色图标 + 一句人话**，不要只变红框。

### 2.4 导航（侧栏）

* 侧栏**与页面同色**、只用一条 1px 分隔线，视觉上"通透"，注意力留给内容。
* 选中项用**主色浅底圆角指示块** + 主色文字；未选中是中性灰。
* 品牌区用一个**微渐变圆角标**（`LinearGradient` 从主色到辅色）就够，不需要大 Logo 图。

### 2.5 标签 / 胶囊 / 指标卡

* 胶囊：`container` 底色 + 同色 16% 的发丝描边 + `on_container` 文字，半径 999。
* 指标卡：**保持白卡**，只让左上角的图标色块承担语义色——
  六张彩底卡片并排会互相打架，一张白卡 + 彩色图标既统一又清爽。

### 2.6 空态 / 加载态 / 浮层

* **空态**：72px 圆角图标容器 + 标题 + 一句引导 + 可选主操作。永远给出"下一步做什么"。
* **加载态**：内容区用**骨架屏**（`ft.Shimmer` + 与真实卡片同尺寸的灰条），
  操作区用**进度环 + 说明**。骨架屏能避免布局跳动，这也是它比转圈更好的原因。
* **浮层提示**：固定深底（`#22262E`）+ 语义色图标 + 浅色文字，两套主题下都清晰。

---

## 3. 布局骨架

```
┌────────┬──────────────────────────────────────────────┐
│ 侧栏96 │  页头（标题/副标题  ←→  动作按钮）           │
│        ├──────────────────────────────────────────────┤
│  导航  │  工具栏（搜索/筛选/排序）                    │
│        │                                              │
│        │  内容（12 列栅格 / 双栏工作台）              │
│  页脚  ├──────────────────────────────────────────────┤
│        │  状态栏（git 状态 · 统计 · 快捷键 · 刷新）   │
└────────┴──────────────────────────────────────────────┘
```

* 页头：左边标题组 `expand=True`，右边动作区 `tight=True`，两端对齐。
* 双栏工作台（提交 / 打包页）：**左栏固定 320**，右栏 `expand=True`，
  右栏内部按"从上到下就是操作顺序"排列。
* 状态栏高度小、字号小（11px CAPTION），信息用图标+文字成对出现，不要堆文字。

---

## 4. Flet 1.0 实战踩坑清单 ⚠️

这一节是本文档最值钱的部分。以下每一条都是**真机上验证过的**，
踩中之后通常没有报错、只有"看起来怪"，很难反查。

### ① 控件渲染后会被冻结，事件里改属性会抛异常

Flet 1.0 的组件在每次渲染结束后会把返回的控件 `_frozen = True`，
之后任何属性写入都抛 `RuntimeError: Frozen controls cannot be updated.`。

**所以"悬停时阴影加深"不能这样写：**

```python
def on_hover(e):                 # ❌ 会抛异常
    e.control.shadow = deeper
    e.control.update()
```

**正确做法：把悬停状态放进组件状态，让它触发一次重渲染。**

```python
hovered, set_hovered = ft.use_state(None)

def handle_hover(event, project):
    entering = str(widgets.event_value(event)).lower() == "true"
    set_hovered(project.id if entering else None)

# 卡片
widgets.surface(..., hovered=hovered == project.id, on_hover=handle_hover)
```

实测：悬停重渲染**不会**打断同页输入框的焦点（`TextField` 的 value 没变就不会产生 patch），
所以这种写法是安全的。要更省性能，可以把卡片本身做成独立子组件，让状态只影响一张卡。

### ② 传了 `style` 就必须显式给 `color`，否则是白字

`ft.Text(..., style=ft.TextStyle(...))` 一旦出现，客户端**不再继承**主题文字色，
缺省色会落到**白色**——浅色主题下就是"完全看不见的字"，而且没有任何报错。

```python
ft.Text("标题", style=ft.TextStyle(height=1.3))            # ❌ 可能是白字
ft.Text("标题", color=ft.Colors.ON_SURFACE, style=...)     # ✅
```

同理，所有显式文本样式（`Theme.text_theme`、`DataTable.data_text_style`、
`Chip.label_text_style`…）都要带上 color。

### ③ `wrap=True` 的行里不能放 `expand` 子项

`Wrap` 不是 `Flex`，子项带 `expand` 会被 Flutter 判为 `ParentDataWidget` 错误。
**release 版客户端只会画出一个灰色方块**，不报错、不写日志，极难定位。

```python
ft.Row(wrap=True, controls=[ft.Container(expand=True), ...])   # ❌ 整块变灰
```

**排查经验**：界面某块渲染成**纯灰矩形**（`#C4C4C4`）＝ 该子树在客户端抛了异常。
把可能的 `wrap + expand`、`expand` 嵌套冲突逐个排除即可。

### ④ 这几个组件的外观字段**不读 Theme**，必须写在控件上

实测（flet 1.0.4）：`NavigationRailTheme.indicator_color`、`NavigationRailTheme.*_label_text_style`、
`ChipTheme.selected_color`、`DialogTheme.bgcolor/shape` 等**不会生效**，
控件仍用客户端默认值（表现为一片突兀的浅蓝）。

```python
ft.NavigationRail(
    indicator_color=ft.Colors.PRIMARY_CONTAINER,        # ✅ 写在控件上才生效
    indicator_shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
    selected_label_text_style=T.text_style(11, ...),
    unselected_label_text_style=T.text_style(11, ...),
)

ft.AlertDialog(bgcolor=T.CARD_COLOR, shape=...)          # ✅ 同理
```

**结论**：`Theme` 负责"没显式指定时的兜底"，关键外观一律在控件上写明。
反过来，`ft.Colors.*` 这类**角色色是可靠的**（它走的是 ColorScheme，能正确解析）。

### ⑤ 字体：显式 TextStyle 必须带上 `font_family`

Material 各处的 `*_text_style` 是**整体替换**而非 merge，漏一处该处就静默回退系统字体。
统一走 `design.text_style()` 构造；画布内文本（flet-charts 的轴标签）也必须显式声明字体。

### ⑥ 输入框描边用 `border=ft.OutlineInputBorder(...)`

`TextField.border_radius` / `Dropdown.border_radius` 在 1.0 已废弃，
统一用状态字典形式的 `border`（见 2.3）。

### ⑦ `fill_color` 是 `ColorValue`，不是状态字典

`ft.TextField.fill_color` / `ft.Dropdown.fill_color` 只接受单个颜色值。
想表达"聚焦时换底色"，得靠 `border` 的状态字典，或者 `focused_bgcolor`。

### ⑧ 多行 `TextField` 必须 `shift_enter=True`

否则 `onFieldSubmitted` 为 null，Enter 提交永远不触发。

### ⑨ 事件处理器一律读 `event.data`

客户端先发事件数据，属性补丁走另一条消息、不保证先到。
例外：`blur` / `focus` 这类**无载荷事件**本来就没有 data，要读控件 state。

### ⑩ 不要把整个页面塞进 `SafeArea` 之外的滚动陷阱

固定高度的图表 + 全量展开的表格用外层滚动；不要让表格 `expand` 后自己滚，
小窗口下会只剩一两行。

---

## 5. 怎么验证"真的做对了"

没有设计稿时，靠**像素级探针**自检比肉眼更可靠：

1. **纯色探针**：抓一张窗口截图，检查关键位置的颜色是否等于令牌值
   （页面底 `#F5F6F9`、卡片 `#FFFFFF`、主色按钮 `#4356C7`、控制台 `#141821`…）。
2. **构图线框**：把截图降采样成几十×几十的字符画，一眼就能看出
   "卡片是不是三列""有没有塌成一条线""某块是不是空了"。
3. **文本可见性**：统计深色像素 / 亮色像素占比，某页接近 0 就说明文字没画出来（白字 bug）。
4. **抓图要用 `PrintWindow(PW_RENDERFULLCONTENT)`**，不要直接抓屏：
   桌面随时会有别的窗口飘到前面，直接抓屏会拍到别人的界面。
5. **确定性驱动**：点按钮前先 `SetForegroundWindow`，坐标一律用**逻辑像素 × 实测缩放**，
   不要写死物理坐标（DPI 一变全错位）。

---

## 6. 交付前自检清单

- [ ] 所有间距、圆角、字号、颜色都取自令牌，没有魔法数字
- [ ] 五级字体层级齐备，正文行高 1.5-1.6，标题字重 ≤600
- [ ] 浅色 / 深色各扫一遍：文字对比度足够，没有"看不见的字"
- [ ] 按钮 / 卡片 / 输入框 / 导航都有悬停、按下、禁用三态
- [ ] 所有输入框聚焦时边框变主色（2px）
- [ ] 加载有骨架屏或柔和动画，不出现空白等待
- [ ] 空态都有"下一步怎么做"的引导
- [ ] 窗口拉大拉小、宽度 <1200 时栅格自动落列，不出现横向滚动
- [ ] 鼠标移过可点区域是手型（`MouseCursor.CLICK`）
- [ ] 关键样式节点有注释说明"为什么是这个值"
- [ ] `ruff check` / `ruff format --check` 通过
- [ ] 运行日志里没有 `渲染失败` / `Traceback`，且**没有出现灰块**（见踩坑 #3）

---

## 7. 令牌速查

```
间距  2 / 4 / 8 / 12 / 16 / 24 / 32 / 40       页面 24 · 模块 24 · 栅格 16 · 卡内 16
圆角  6 / 8 / 10 / 14 / 18 / 999               输入 8 · 按钮 10 · 卡片 14 · 弹窗 18
字号  22 / 15 / 13 / 12 / 11                   权重 600 / 600 / 400 / 500 / 400
色彩  主色 #4356C7 · 辅色 #5B6478 / #0E7C6B · 中性 #F5F6F9 → #1A1C22
阴影  静止 0.05 · 悬停 0.10 · 浮层 0.16（不透明度，向下 offset）
动效  150 / 200 / 280ms，EASE_OUT
```