# 喜鹊儿 App（青果系统）协议笔记

青果软件「喜鹊儿」的接口笔记，外加一份能跑的最小实现。

这套 App 在很多高校用于查课表、上课签到、看成绩。它把所有业务动作压进同一个 JSP 控制器，用 `action` / `step` 两个参数路由，请求体外面再套一层自定义信封。这类结构在国内高校信息化产品里很常见，所以下面的方法换个学校、换个版本大多还站得住，具体参数名和常量则未必。

仓库两块：

- **`docs/`** —— 三篇笔记。讲接口是怎么被摸清的：判据、反例、哪些结论当时没验证
- **`kingosoft/`** —— 同一套结论的封装。四个模块一条链路，只依赖 `requests`

## 三篇笔记

| 文档 | 内容 |
|---|---|
| [登录链路](docs/01-login.md) | 学校怎么路由、版本门是下限还是精确匹配、会话怎么探测、多账号会话池 |
| [课表结构](docs/02-timetable.md) | 天桶命名的坑、排课计划串为什么不能用来过滤、周次怎么换算、两条互斥分支怎么选 |
| [签到机制](docs/03-checkin.md) | 三种签到方式的校验落在客户端还是服务端、受理不等于落库、三层判定 |

三篇是递进的：登录拿会话 → 课表定位到「哪门课、哪一节」→ 签到用这组参数提交。每篇末尾都有一节「未验证的部分」，那些是真实盲区 —— 写出来比装作全知更有用。

## 代码

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

| 文件 | 职责 |
|---|---|
| `envelope.py` | 请求外壳。`Envelope` 协议 + 明文实现，外壳编码按版本替换 |
| `client.py` | 学校解析、登录、`call()`、token 失效自动重登、网络层退避 |
| `kb.py` | 学期、单周课表、天桶归一、今日课程、班级反查 |
| `checkin.py` | 签到状态、三种提交、距离计算、落库核验 |

失败抛 `ApiError`，不静默吞。几个最容易踩坏的地方都做成了类型上的约束，而不是注释里的提醒：

- **`State.active` 只认「签到中」**。「未发起」「已结束」一律 `False`，不会误提交
- **`jc_hit()` 用区间交集比较节次**，`"3-4"` 与 `"7-8"` 不会互相认领 —— 同一个教学班一天常有多节课
- **`verify()` 把「服务端说成功」和「考勤真有记录」分开返回**，前者不构成证据

外壳编码是留白的。`BoardEnvelope._encode()` 停在 `NotImplementedError`：纯 Python 复刻客户端的字符算术与签名，每个版本都可能变，硬编码进库只会让库更快过期。判别方法在 [登录链路](docs/01-login.md)，实现按你手上的版本补。

## 参考

- [kingosoft_api](https://github.com/lizhengqiang/kingosoft_api) —— 同产品的接口实现（Java / JavaScript）。想看全量接口、想把更多功能调通，去那边
- [xiqueer](https://github.com/GangJust/xiqueer) —— 上面那个项目的上游，逆向工作的源头

本仓库的每条结论都对过它们的源码与实机响应；与参考实现不一致的地方，正文里注明了实测差异。

## 致谢

感谢 [kingosoft_api](https://github.com/lizhengqiang/kingosoft_api) 与 [xiqueer](https://github.com/GangJust/xiqueer) 的先行工作 —— 加密链路与部分接口形态的初始方向来自它们。

## License

MIT
