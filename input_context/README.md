# input_context/

Deposite aqui os arquivos de contexto científico da sua sessão antes de executar
`geminiclaw`. O sistema carrega e processa automaticamente esta pasta antes de
iniciar a sessão — não é necessário nenhum flag no CLI.

Formatos suportados:
- `context.md`, `.txt`, `.rst` — objetivo, hipóteses, instruções (chunked se > 50.000 chars)
- `.pdf`, `.docx`, `.pptx` — artigos e documentos de referência
- `.csv`, `.tsv`, `.xlsx`, `.xls`, `.ods` — datasets (resumidos: schema, amostra, estatísticas)
- `.json`, `.jsonl` — dados estruturados ou schemas
- `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp` — imagens (OCR local ou Gemini Vision)

Após a sessão, uma cópia imutável do que foi usado fica em
`outputs/<session_id>/input_snapshot/`. Esta pasta (`input_context/`) NÃO é
limpa automaticamente — rode `geminiclaw clear-context` quando quiser
prepará-la para a próxima sessão.
