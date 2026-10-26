## ADDED Requirements

### Requirement: Complete immutable record aggregation
交付 SHALL 保留完整 recordIds/sourceIds，并在当前全部来源授权通过后向 read/UI/download 返回完整原 records；不得截断负结果或用影子副本绕过原来源。

#### Scenario: Two normal records exceed the former aggregate guard
- **WHEN** 两条各约 7.5 KiB 的合法终稿连同封装合计超过 16 KiB、但完整 ZIP 仍在既有 delivery 上限内
- **THEN** create/read/download 均成功，原正文逐字等值且重试返回同一 id；持久 body 不复制 records

#### Scenario: Long referenced body and old inline manifest
- **WHEN** 交付包含 R1 长中文正文或读取旧含 records 副本的 manifest
- **THEN** records 完整还原；正文载体不另作精选证据导出，原 sourceIds 不减少

### Requirement: One actual export budget
交付 SHALL 使用既有 maximum 限制完整 UTF-8 manifest、精选附件与实际 ZIP 开销；create/read/download 对相同来源、配置和字节 SHALL 得到同一可交付结果。

#### Scenario: Actual package exceeds the limit
- **WHEN** 原正文合法但完整包超过 maximum，包括仅 ZIP 头部造成的超限
- **THEN** 返回 413 RESEARCH_DELIVERY_TOO_LARGE，失败 create 不留 delivery 或成功回执，不截断/半包

### Requirement: Current original source and evidence authority
交付 SHALL 在每次读取或导出时核对当前全部来源和精选证据的身份、大小及字节完整性，不因历史成功免检。

#### Scenario: A non-cited dependency is withdrawn
- **WHEN** 任一原 sourceId 撤回或缺失，或精选制品损坏
- **THEN** 保留原 404/409 边界，read/download 不返回缓存正文，list 不泄露撤回内容；不得把此类错误伪装成预算不足
