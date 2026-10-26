## 喜鹊儿 App（青果系统）协议笔记

**文档讲思路，代码给最小封装。** 记录怎么把一套集中式 JSP 控制器的接口摸清楚：从哪下手、怎么验证、结论是什么、工程上会踩什么坑。代码只覆盖协议本身，不含调度、推送与界面。

#### 参考项目

> - [kingosoft_api](https://github.com/lizhengqiang/kingosoft_api "kingosoft_api") —— 同产品的接口封装实现（Java / JavaScript）。**本项目与它互补**：那边回答「怎么调通」，这边回答「为什么这么调、哪些坑必须先知道」
> - [xiqueer](https://github.com/GangJust/xiqueer "xiqueer") —— 上面那个项目的上游，逆向过程的源头

这里的每一条结论都对过它的反编译代码与实机响应，凡是与参考实现不一致的地方，都在正文里写明了实测差异。

#### 三篇

> - [登录链路](docs/01-login.md) —— 学校路由、版本门是下限校验还是精确匹配、会话四探测、多账号会话池
> - [课表结构](docs/02-timetable.md) —— 天桶命名陷阱、排课计划串为什么不可用来过滤、周次换算、两条互斥分支的判据
> - [签到机制](docs/03-checkin.md) —— 三种签到方式的验证发生在客户端还是服务端、受理 ≠ 落库、三层判定、引擎设计

#### 代码

`kingosoft/` 是同一套结论的最小实现，四个模块一条链路，只依赖 `requests`：

| 文件 | 职责 |
|---|---|
| `envelope.py` | 请求外壳。定义 `Envelope` 协议 + 明文实现，外壳编码按版本替换 |
| `client.py` | 学校解析、登录、`call()`、token 失效自动重登、网络层退避 |
| `kb.py` | 学期、单周课表、天桶归一、今日课程、班级反查 |
| `checkin.py` | 签到状态、三种提交、距离计算、落库核验 |

```python
from kingosoft import Client, Checkin
from kingosoft import kb

c = Client(xxdm="SCHOOL_CODE", login_id="STUDENT_NO", password="PASSWORD")
c.login()

terms = kb.terms(c)
table = kb.week_table(c, terms[0]["id"])   # week=0 → 自动探测当前周
ck = Checkin(c, xnxq=terms[0]["id"])

for course in table.today():
    st = ck.state(course)
    if st.active and st.qdfs in ("1", "2"):   # 定位 / 手势
        ck.submit_location(course, st)
        print(ck.verify(course))              # 受理 ≠ 落库，必须回查
```

失败一律抛 `ApiError`，不静默吞。三处关键判据都落在类型里：
`State.active` 只认「签到中」，`jc_hit()` 用区间交集避免同班串节，
`verify()` 把「服务端说成功」和「考勤真有记录」分开。

**刻意留白**：外壳编码（`BoardEnvelope._encode`）留成 `NotImplementedError`。
纯 Python 复刻它要移植客户端里的一段字符算术与签名，而且每个版本都可能变——
硬编码进库只会让库更快过期。判别方法见 [登录链路](docs/01-login.md)，
具体实现按你手上的客户端版本补。

#### 与参考实现的区别

| | kingosoft_api | 本项目 |
|---|---|---|
| 形态 | Java / JavaScript 全量接口代码 | Markdown 笔记 + 协议最小封装 |
| 目标 | 调通尽可能多的接口 | 讲清接口的结构与判据 |
| 加密 | 直接给实现 | 只说明判别方法（编码 ≠ 加密） |
| 覆盖面 | 登录、课表、成绩、学情、培养方案等 | 登录、课表、签到三块 |
| 适合谁 | 想直接调用 | 想自己复刻 / 排查为什么调不通 |

#### 范围与边界

不包含任何真实账号、学号、姓名、学校、token、密钥。代码只做协议封装——自动调度、消息推送、前端界面都不在仓库里。
每篇末尾都有一节「未验证的部分」，那些是真实存在的盲区 —— 写出来比装作全知有用。

#### 环境说明

文档描述的是一套集中式控制器架构：所有业务动作打同一个入口，用 `action` / `step` 两个参数路由，外层再套一层自定义信封。

这类架构在国内高校信息化产品里很常见，本文的**方法**对同类系统普遍适用，但具体参数名、常量、分支条件都属于某一版本客户端的实现细节，会随版本变化。

#### 致谢

感谢 [kingosoft_api](https://github.com/lizhengqiang/kingosoft_api) 与 [xiqueer](https://github.com/GangJust/xiqueer) 的先行工作 —— 加密链路与部分接口形态的初始方向来自它们，本项目在其基础上补了实测验证与判据整理。

#### License

MIT
