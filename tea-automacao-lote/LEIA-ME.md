# Automação de extração dos 3.141 apps

O pacote adiciona um extrator em lote independente, sem alterar o código anterior.
Usa Python 3.10+ e Ollama local. Não exige pip/venv/npm para executar ou testar.

Leia COMANDOS.md, que contém aplicação, teste, preparação dos 3.141, teste com
três apps, execução completa e retomada. O mesmo guia será instalado em
docs/AUTOMACAO-3141.md no repositório.

Inclui patch, cópia integral dos arquivos adicionados em codigo/, aplicador com
verificação de integridade e VALIDACAO.json.

Foi validado o carregamento da coleta real (3.141 apps, 5.122 partes brutas).
O filtro por menção explícita selecionou 713 apps e 1.303 partes para extração;
2.428 apps não mencionam explicitamente uma condição reconhecida. Esses números
não são avaliação semântica e o filtro lexical pode errar. O software foi testado
com respostas simuladas; não houve inferência com modelo real nem acesso ao
servidor UTFPR neste ambiente.

Os resultados dos 100 apps produzidos anteriormente pelo ChatGPT continuam
separados. Não são rotulados como saídas do modelo local.

Não houve commit. Os dados originais de coleta não são alterados.
