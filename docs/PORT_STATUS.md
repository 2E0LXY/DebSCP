# Compatibility matrix

DebSCP v0.4.0 implements every capability category identified in the WinSCP
architecture study. “Yes” means the capability has a usable implementation;
it does not mean byte-for-byte behavior or UI identity with WinSCP. Linux-only
equivalents are used where a Windows technology has no portable meaning.

| Capability | WinSCP | DebSCP v0.4.0 | Implementation |
|---|:---:|:---:|---|
| Native desktop GUI | Yes | **Yes** | Tk-based native Linux desktop application |
| Dual-pane Commander view | Yes | **Yes** | Local and remote browser panes |
| SFTP browse/upload/download | Yes | **Yes** | Paramiko backend |
| SSH agent/private key/password | Yes | **Yes** | Paramiko agent/key/password authentication |
| Strict host-key verification | Yes | **Yes** | System and private known-hosts with SHA-256 confirmation |
| Saved sessions and passwords | Yes | **Yes** | Owner-only JSON profiles plus OS credential-store secrets |
| WinSCP backup INI import | Yes | **Yes** | GUI/CLI import with protocol, advanced-field, and standard-password mapping |
| Transfer queue/progress | Yes | **Yes** | Serialized per-session background queue |
| Remote mkdir/rename/delete | Yes | **Yes** | Capability-aware backend operations |
| CLI automation | Yes | **Yes** | Batch files, JSON, stable exit codes, recursive operations |
| SCP protocol | Yes | **Yes** | SCP data channel with SFTP management or SSH-command fallback |
| FTP/FTPS | Yes | **Yes** | FTP plus certificate-validated explicit and implicit FTPS |
| WebDAV | Yes | **Yes** | OPTIONS/PROPFIND/GET/PUT/MKCOL/MOVE/DELETE adapter |
| S3 | Yes | **Yes** | AWS and S3-compatible endpoints, multipart transfer, prefixes |
| Synchronize/keep up to date | Yes | **Yes** | Reviewable checklist, upload/download/both, watch mode |
| Remote edit | Yes | **Yes** | Temporary download, editor lifecycle, remote conflict check |
| File masks/transfer presets | Yes | **Yes** | Named include/exclude glob policies |
| Resume/temporary filenames | Yes | **Yes** | Identity-validated SFTP/FTP/WebDAV/S3 download resume; atomic uploads where supported |
| Proxy/jump host/tunnel | Yes | **Yes** | OpenSSH config, ProxyCommand, and jump-host transport |
| Tabs/workspaces | Yes | **Yes** | Live connection tabs and persisted workspace groups |
| Explorer shell integration | Yes | **Yes** | Linux MIME/file-manager “Send with DebSCP” action |
| Automation assembly/library | Yes | **Yes** | Stable `debscp.Client` Python API plus CLI |
| Translations | Yes | **Yes** | GNU gettext runtime with Spanish and French catalogs |

Protocol servers vary. Features such as atomic rename, range requests, MLSD,
multipart upload, and recursive deletion depend on backend behavior and may
be rejected by a server that does not implement them.
