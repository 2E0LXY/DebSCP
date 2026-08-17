# Port status and compatibility matrix

DebSCP v0.1.0 establishes the Linux application, security model, backend
contract, GUI/CLI surfaces, tests, and Debian release pipeline. It is not a
claim of full WinSCP parity.

| Capability | WinSCP | DebSCP v0.1.0 | Planned direction |
|---|:---:|:---:|---|
| Native desktop GUI | Windows | Linux/Tk | Continue native Linux accessibility/polish |
| Dual-pane Commander view | Yes | Yes | Multi-select and drag/drop |
| SFTP browse/upload/download | Yes | Yes | Resume and recursive transfers |
| SSH agent/private key/password | Yes | Yes | Hardware-key validation |
| Strict host-key verification | Yes | Yes | Key-change management UI |
| Saved sessions, no saved password | Yes | Yes | Secret Service integration (opt-in) |
| Transfer queue/progress | Yes | Yes | Pause, cancel, parallel sessions, retry |
| Remote mkdir/rename/delete | Yes | Yes | Recursive safe delete and permissions |
| CLI automation | Yes | Basic | Batch files, structured output, exit-code spec |
| SCP protocol | Yes | No | OpenSSH `scp` adapter after compatibility tests |
| FTP/FTPS | Yes | No | Separate capability-aware backend |
| WebDAV | Yes | No | Standards-based backend |
| S3 | Yes | No | Object-store-native semantics |
| Synchronize/keep up to date | Yes | No | Checklist-first sync engine |
| Remote edit | Yes | No | Temp-file lifecycle and conflict checks |
| File masks/transfer presets | Yes | No | Shared copy policy model |
| Resume/temporary filenames | Yes | No | Atomic upload/download policy |
| Proxy/jump host/tunnel | Yes | No | SSH config and ProxyJump support |
| Tabs/workspaces | Yes | No | Multi-session manager |
| Explorer shell integration | Windows | N/A | Linux file-manager actions/portal |
| .NET assembly | Yes | N/A | Stable CLI and future Python API |
| Translations | Extensive | No | gettext catalog |

Before 1.0, the project needs recursive transfers, cancellation, atomic/resumed
copies, tests against multiple SSH servers, accessibility review, integration
tests, a threat-model review, and at least one additional protocol backend.

