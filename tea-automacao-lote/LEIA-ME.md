# Classificação e extração dos 3.141 apps

O pacote atualiza a automação para classificação seguida de extração. Usa Python
3.10+ e Ollama local. Não exige pip/venv/npm para executar ou testar. O instalador
só substitui arquivos v2 cujos hashes correspondam exatamente à versão conhecida;
não altera os resultados nem o checkpoint v2.

Leia COMANDOS.md, que contém aplicação, teste, preparação dos 3.141, teste com
três apps, classificação LLM, extração, execução completa e retomada. O mesmo guia
será instalado em docs/AUTOMACAO-3141.md no repositório.

Inclui patch, cópia integral dos arquivos adicionados em codigo/, aplicador com
verificação de integridade e VALIDACAO.json.

O plano da coleta atual prevê 3.141 classificações e até 5.122 partes de extração
caso todos os apps sejam relevantes. A classificação por Ollama usa título e
descrição completa; não há pré-filtro lexical. `not_relevant` não é extraído e
`uncertain` fica para revisão. O software foi testado com respostas simuladas; não
houve inferência com modelo real nem acesso ao servidor UTFPR neste ambiente.

Os resultados dos 100 apps produzidos anteriormente pelo ChatGPT continuam
separados. Não são rotulados como saídas do modelo local.

Não houve commit. Os dados originais de coleta não são alterados.
