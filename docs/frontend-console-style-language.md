# Frontend Console Style Language

本文件沉淀当前 `obs-local` 前端已验证通过、且用户明确认可的视觉语言。

适用于：

- 控制台
- 观测台
- 仪表盘
- 实时运行态页面

## 1. 风格定位

目标气质：

- 专业
- 克制
- 高级
- 有产品感
- 工程控制台，而不是通用后台表单页

不追求：

- 花哨营销页
- 重型企业组件库默认味道
- 浏览器原生控件感
- 浅色工具页或低保真管理台

## 2. 视觉母题

整体视觉应围绕以下母题展开：

- 深色控制台底色
- 青蓝冷光品牌色
- 玻璃感渐变面板
- 细边框 + 大圆角
- 低噪音微动效
- 单色系信息分层，而不是大面积高饱和撞色

## 3. 色彩语言

主色方向：

- 品牌主色：青蓝偏冷
- 文字主色：偏冷白
- 次级文字：蓝灰
- 面板底色：深海军蓝 / 深石墨蓝
- 状态色：
  - 成功：偏青绿，不要荧光绿
  - 警告：偏琥珀，不要亮黄
  - 危险：偏珊瑚红，不要纯红

规则：

- 背景层次靠透明度、渐变、边框和阴影建立，不靠大块纯色切割
- 品牌色用来点亮焦点，不用来涂满整块区域
- 高亮状态必须克制，避免整页彩条化

## 4. 布局语言

- Hero 区应有强识别度，但不能压垮主数据区
- 品牌区、状态区、主列表区、辅助面板区应当形成稳定网格
- 卡片之间靠间距、阴影、边框强度做层次，不靠粗暴底色区分
- 同一行控件保持一致高度、圆角、内边距和视觉重量

推荐结构：

- 上方：品牌 + 实时状态 + 全局控制
- 中间：统计卡
- 下方：主信息区 + 辅助信息区
- 侧边：项目切换或上下文导航

## 5. 组件语言

### 5.1 状态类元素

- 优先使用 pill / badge / segmented control
- 避免朴素矩形按钮和浏览器原生下拉
- 状态件应显得“轻而准”，而不是“大而吵”

### 5.2 选择器与筛选器

- 少量离散项：segmented control
- 多选项选择：headless dropdown / listbox
- 可输入筛选：headless combobox
- 禁止直接暴露原生 `select`、`option`、`datalist` 成品感

### 5.3 列表与详情

- 列表项要有悬停与选中态，但不出现过强闪烁
- 详情抽屉延续主界面材质，不单独变成另一套风格
- 技术明细应允许“双层表达”：
  - 语义化标题
  - 原始技术值

## 6. 字体与文字

- 标题使用更有张力的 display 字体
- 正文使用清晰的 sans 字体
- 技术字段使用 mono 字体

规则：

- 大标题拉开层次，正文保持克制
- 不要满屏大写英文标签
- 文案简短，避免后台式口号堆砌
- 中文界面可以保留英文技术值，但不应让用户先撞上技术细节再理解语义

## 7. 动效

允许：

- 页面或卡片轻微上浮进入
- 品牌块微弱呼吸光
- 标签轻微漂浮
- hover / focus 的短促高亮反馈

禁止：

- 无意义闪烁
- 高频跳动
- 大范围位移动画
- 抢夺用户注意力的动效

原则：

- 动效是“气质增强器”，不是主角

## 8. 工程实现建议

- 交互底座优先 headless，不直接引重型视觉组件库统一接管样式
- 视觉统一通过自定义 token、组件皮肤和少量基础控件完成
- 所有运行态/多语言文案都走稳定 key，不把自然语言写入内部状态
- 同类页面复用以下三层：
  - design tokens
  - 基础交互控件
  - 页面骨架组件

## 9. 当前基线实现

当前已验证通过的实现基线可参考：

- Tokens: [obs-local/frontend/src/styles/tokens.css](/E:/github/mykms/obs-local/frontend/src/styles/tokens.css)
- Base: [obs-local/frontend/src/styles/base.css](/E:/github/mykms/obs-local/frontend/src/styles/base.css)
- Hero shell: [obs-local/frontend/src/components/AppShell.vue](/E:/github/mykms/obs-local/frontend/src/components/AppShell.vue)
- Dashboard: [obs-local/frontend/src/views/DashboardView.vue](/E:/github/mykms/obs-local/frontend/src/views/DashboardView.vue)
- Headless controls:
  - [ControlSelect.vue](/E:/github/mykms/obs-local/frontend/src/components/ControlSelect.vue)
  - [ControlCombobox.vue](/E:/github/mykms/obs-local/frontend/src/components/ControlCombobox.vue)

## 10. 一句话约束

如果一个控件或局部区域看起来像“浏览器默认控件、通用后台模板、重型组件库默认皮肤”，那它就不属于这套风格。
