# serde / 序列化 / derive / 属性 / 自定义 / 零拷贝 / 格式

serde 是 Rust 序列化的事实标准:`derive` 一行搞定大多数类型,属性微调,真需要时自定义 (de)serialize。本域讲怎么把类型映射到 JSON/TOML/二进制并保持版本兼容。

适用:给类型加 `Serialize`/`Deserialize`、改字段名/大小写、处理缺省与可选、enum 怎么表示、零拷贝借用反序列化、选格式 crate、加字段不破坏老数据。

---

## 起步:derive + 容器属性

- **`#[derive(Serialize, Deserialize)]`** 覆盖绝大多数 struct/enum,无需手写。
- **`rename_all`**:统一字段命名风格,把 Rust 的 `snake_case` 映射到 JSON 的 `camelCase`(或 `kebab-case`/`PascalCase`/`SCREAMING_SNAKE_CASE`)。容器级一次设好,别逐字段 `rename`。→ [`serde-rename-all`](rules/serde-rename-all.md)
- **`rename`**(字段级):个别字段名和外部协议对不上时单独改(如 `type` 是关键字)。
- **`deny_unknown_fields`**:严格模式,遇到未知字段报错——见下"版本兼容"取舍。→ [`serde-deny-unknown-fields`](rules/serde-deny-unknown-fields.md)

## 常用字段属性

| 属性 | 作用 | 规则 |
|---|---|---|
| `default` | 缺字段时用 `Default`(或指定 fn),反序列化更宽容 | [`serde-default-compat`](rules/serde-default-compat.md) |
| `skip_serializing_if = "Option::is_none"` | 空值不输出,JSON 更干净 | [`serde-skip-empty`](rules/serde-skip-empty.md) |
| `flatten` | 把内嵌 struct 的字段提到父层(组合配置、捕获额外字段到 map) | [`serde-flatten`](rules/serde-flatten.md) |
| `serialize_with` / `deserialize_with` | 单字段自定义转换,不必给整个类型写 impl | [`serde-custom-with`](rules/serde-custom-with.md) |
| `with = "module"` | 同时定制 ser + de(模块内含两函数) | — |
| `borrow` | 零拷贝借用(见下) | — |

## enum 的四种表示(选对协议形状)

同一个 enum,wire 格式可以差很多,务必和对端协议对齐:

- **externally tagged**(默认):`{"Variant": {...}}`——变体名作外层 key。
- **internally tagged**:`#[serde(tag = "type")]` → `{"type": "Variant", ...field...}`,字段平铺,常见于 JSON API。
- **adjacently tagged**:`#[serde(tag = "t", content = "c")]` → `{"t": "Variant", "c": {...}}`。
- **untagged**:`#[serde(untagged)]` → 无标签,按结构**逐个变体试匹配**(灵活但有歧义/性能代价,顺序敏感)。
- → [`serde-enum-representation`](rules/serde-enum-representation.md)

## 自定义 (de)serialize

- **优先用属性**:`serialize_with`/`deserialize_with`/`with` 解决单字段(时间格式、十六进制、自定义编码)就别手写整个 impl。→ [`serde-custom-with`](rules/serde-custom-with.md)
- **手写 impl**:类型映射和默认 derive 差太远(完全自定义 wire 格式)才实现 `Serialize`/`Deserialize`;`Deserialize` 手写需要 `Visitor`,较繁琐,先确认属性方案真不够。
- **反序列化时校验**:别先反序列化成裸结构再到处校验;用 `#[serde(try_from = "RawType")]` 把"解析即验证"做进类型边界,得到的值天然合法。→ [`serde-try-from-validate`](rules/serde-try-from-validate.md)、并见 [`api-design.md`](api-design.md) 的 parse-don't-validate

## 零拷贝借用(`#[serde(borrow)]`)

- 反序列化出的 `&str`/`&[u8]` 可直接借用输入缓冲,免分配:`struct S<'a> { #[serde(borrow)] name: &'a str }`。
- 适合短命、不需 own 数据的高吞吐解析;带 `'a` 的类型不能活过输入缓冲——和所有权权衡,见 [`ownership-lifetimes.md`](ownership-lifetimes.md)(`own-cow-conditional`)。`Cow<'a, str>` 是"能借则借、需要时才 own"的折中。

## 格式 crate(选数据格式)

| 格式 | crate | 适用 |
|---|---|---|
| JSON | `serde_json` | Web API、配置、人读 |
| TOML | `toml` | 配置文件(Cargo.toml 即是) |
| YAML | `serde_yaml`(注意维护状态) | 配置;不确定查 docs.rs |
| MessagePack | `rmp-serde` | 紧凑二进制、跨语言 |
| CBOR | `ciborium` | 标准化二进制 |
| bincode | `bincode` | Rust↔Rust 内部、最快最紧凑(非自描述,两端类型须一致) |

> `bincode` 非自描述格式,序列化和反序列化端的类型布局必须匹配,不适合跨版本长期存储;长期/跨语言用 JSON/MessagePack/CBOR。具体能力与版本以 docs.rs 为准。

## 版本兼容(加字段不炸老数据)

- **加字段给 `default`**:新增字段标 `#[serde(default)]`,老数据缺该字段也能反序列化。→ [`serde-default-compat`](rules/serde-default-compat.md)
- **`deny_unknown_fields` 的取舍**:加上它能尽早抓拼写错/脏数据,但**牺牲前向兼容**——老程序遇到新版多出的字段会报错。对外、需平滑演进的 schema 通常**不加**;内部强校验的配置才加。→ [`serde-deny-unknown-fields`](rules/serde-deny-unknown-fields.md)
- 删/改字段名是破坏性变更;过渡期用 `alias` 兼容旧名。

## newtype 透明:`#[serde(transparent)]`

- newtype 包装(`struct UserId(u64)`)默认会序列化成 `{"0": 42}` 之类;`#[serde(transparent)]` 让它直接序列化为内层值(`42`),wire 上"透明无包装"。配合类型安全 newtype 用,见 [`api-design.md`](api-design.md) 的 `api-newtype-safety`/`type-newtype-ids`。

## 典型坑

- **enum 表示和对端不一致**:默认 externally tagged,但很多 JSON API 要 internally tagged(`tag = "type"`),不设就两边对不上。
- **`untagged` 顺序/歧义**:多个变体结构相近时匹配到错的那个;能用显式 tag 就别 untagged。
- **`deny_unknown_fields` 砍了前向兼容**:对外协议加了它,客户端升级加字段就把老服务打挂。
- **`flatten` + `deny_unknown_fields` 冲突**:两者一起用行为微妙(flatten 需要"放行"未知字段),易踩坑——查文档确认。
- **borrow 生命周期传染**:`S<'a>` 借了输入缓冲,缓冲先 drop 就编不过;需要 own 时改 `String`/`Cow`。
- **bincode 跨版本存档**:类型变了读不回老数据;长期存储别用非自描述格式。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **serde(`serde-*`,8 条)** 类
- "解析即验证"与 newtype 见 [`api-design.md`](api-design.md);带生命周期的借用/`Cow` 见 [`ownership-lifetimes.md`](ownership-lifetimes.md)
- serde 作 optional feature 暴露见 [`project-cargo.md`](project-cargo.md)(feature 加性原则)

## 参考

- serde 官方指南(serde.rs)——属性、enum 表示、自定义 impl 的权威文档
- `serde_json` / `toml` / `rmp-serde` / `ciborium` / `bincode` 各自 docs.rs(API、版本、维护状态以文档为准)
- The Book ch.关于 trait 的章节(理解 derive 背后的 trait impl)
