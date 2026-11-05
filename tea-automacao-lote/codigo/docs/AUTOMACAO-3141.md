# Extração automática dos 3.141 apps

Esta automação usa somente Python 3.10+ e a API do Ollama configurada. Não precisa
de venv, pip, npm, assinatura de API ou coleta adicional da Google Play. O Ollama
e um modelo local instalado precisam estar disponíveis na máquina que vai rodar
as gerações. Não há download automático de modelo.

O novo comando é independente do extrator anterior para preservar seus patches e
resultados. Nenhum arquivo antigo do projeto é substituído. Nenhum commit é feito.

## O que executa

1. Lê os JSONs locais, preserva os dez grupos de busca e deduplica por appId.
2. Congela texto completo, fontes, hashes e origem. Não faz filtro de TEA ou de
   relevância. Os grupos indicam origem da busca, não diagnóstico ou adequação.
3. Divide descrições em partes com orçamento conservador de contexto. Todos os
   caracteres não brancos são preservados. IDs e offsets apontam para a fonte.
4. Chama o modelo para obter ações e IDs de evidência. O Python copia a evidência;
   não usa aproximação textual nem inventa citações para corrigir uma previsão.
5. Salva cada parte validada em SQLite. Repetir o comando retoma pendências sem
   gerar novamente as partes concluídas, inclusive em um app parcialmente feito.
6. Exporta CSVs, JSONL, contagens e uma tabela inicial para normalizar nomes.

Respostas vazias ficam como `review_empty` quando o app inteiro não tem candidatas.
Isso não comprova ausência de funcionalidades. `complete` significa apenas que
todas as partes passaram pela validação estrutural e literal. A correção semântica
e as omissões continuam exigindo avaliação humana de uma amostra.

## Aplicar e testar o código

Baixe e extraia o ZIP antes dos comandos. No repositório em que você já trabalha:

```bash
unzip ~/Downloads/tea-automacao-lote.zip -d ~/Downloads &&
cd ~/Documentos/github/eng-soft-empirica/tea-scrapper &&
bash ~/Downloads/tea-automacao-lote/aplicar.sh &&
python3 -m unittest discover -s batch_tools -p 'test_*.py' -v
```

O aplicador verifica os arquivos do pacote, aceita reaplicação idêntica e recusa
colisões com código diferente. Não usa reset, checkout, clean ou aplicação forçada.
É compatível com as versões anteriores porque adiciona somente arquivos novos.

Se estiver no servidor e o repositório tiver outro endereço, entre nele primeiro
e execute os mesmos comandos a partir de `bash .../aplicar.sh`. Copie o pacote e
os JSONs para o servidor ou use o repositório que o Pedro já possui lá. O caminho
local da sua máquina não existe automaticamente no servidor.

## Preparar todos os apps, sem chamar a IA

Na raiz do repositório:

```bash
python3 batch_tools/tea_batch.py prepare \
  --results output/results_2026-10-19 \
  --out analysis/lote-3141 \
  --expect-apps 3141

python3 batch_tools/tea_batch.py plan --out analysis/lote-3141
```

Na coleta enviada foram encontrados 3.141 apps, zero descrições vazias e 5.122
partes com as opções padrão. Esses números são preparação, não resultados de LLM.
Se a coleta for outra, `--expect-apps 3141` evita executar o conjunto errado.

## Primeiro teste com o modelo real no servidor

Veja `ollama list` na máquina que executará a extração. Abaixo usamos `qwen2.5:3b`,
que estava instalado no seu notebook. Ele precisa estar instalado também no
servidor para usar esse nome lá. O exemplo não atesta a qualidade desse modelo:
ele já apresentou omissões no teste anterior. Troque o nome pelo modelo local
que a equipe escolher; faça isso antes da primeira geração desta pasta.

```bash
python3 batch_tools/tea_batch.py doctor --model qwen2.5:3b

python3 batch_tools/tea_batch.py run \
  --out analysis/lote-3141 --model qwen2.5:3b \
  --app-id uk.co.mymolehillmountain.autistica \
  --app-id com.dmwaresolutions.meuabinha \
  --app-id com.learnItalianforbeginners.freerd

python3 batch_tools/tea_batch.py status --out analysis/lote-3141
```

Esse comando testa três apps dentro do corpus completo e deixa os outros pendentes.
`apps` continuará mostrando 3.141, com três tecnicamente concluídos se não houver
falhas. A seleção de três não altera a identidade da execução nem impede retomar.

Abra `analysis/lote-3141/funcionalidades.csv` e confira especialmente Molehill
Mountain. Sua descrição anuncia acompanhamento de preocupações, gráfico de
check-ins, consulta de check-ins anteriores, dicas de ansiedade e atividades de
TCC. Não aceite uma resposta vazia como demonstração de qualidade. Essa lista
serve como verificação de desenvolvimento, não padrão ouro independente.

O app de italiano pode ter funcionalidades mesmo sem ser relevante para TEA.
Neste lote queremos extrair capacidades de todos os grupos; não existe filtro
automático que elimine o app antes da extração.

`mean_completed_app_seconds` informa tempo observado, incluindo tentativas.
`estimated_serial_hours_remaining` é extrapolação aproximada para execução
serial, sem garantia. Três apps não representam todos os tamanhos e dificuldades.
O tempo depende do modelo e do servidor; não foi prometida execução em minutos.

## Executar o restante dos 3.141

Se o primeiro teste tiver fluxo e qualidade aceitáveis para desenvolvimento:

```bash
python3 batch_tools/tea_batch.py run \
  --out analysis/lote-3141 --model qwen2.5:3b --retry-errors
```

Use exatamente a mesma pasta e configuração para retomar. Os três apps do teste,
se já concluídos, não serão gerados novamente. Ctrl+C encerra o agendamento e
preserva o checkpoint; depois repita o comando. Um encerramento forçado pode
repetir uma chamada que terminou, mas ainda não havia sido salva. Resultados já
confirmados no SQLite são preservados.

O padrão usa um worker para não multiplicar a demanda de memória e a fila do
modelo. `--workers 2` permite duas chamadas em paralelo, mas só vale aumentar se
o servidor suportar e a medição mostrar ganho. Workers, timeout e seleção de
apps podem mudar ao retomar. Modelo, digest, versão, prompt, código ou opções de
geração diferentes exigem uma nova pasta preparada com os mesmos JSONs.

Retentativas são limitadas: no máximo duas chamadas por parte por execução.
Um timeout de geração não é repetido automaticamente e interrompe o agendamento
de novas partes, para não deixar a máquina repetindo chamadas lentas por horas.
`--retry-errors` autoriza tentar erros anteriores outra vez; sucessos não são
repetidos. HTTP 400/401/403/404 interrompe novo agendamento. Três falhas seguidas
de transporte também interrompem o lote para não insistir em serviço indisponível.
Leia o erro e corrija a causa antes de repetir indefinidamente.

Para deixar o processo rodando mesmo após encerrar a sessão SSH, opcionalmente:

```bash
nohup python3 batch_tools/tea_batch.py run \
  --out analysis/lote-3141 --model qwen2.5:3b --retry-errors \
  > analysis/lote-3141/execucao.log 2>&1 &
```

Não inicie outra geração na mesma pasta enquanto essa estiver ativa. O lock impede
dois escritores. Nesse caso, acompanhe `tail -n 20 analysis/lote-3141/execucao.log`
ou use `status --out analysis/lote-3141`, que consulta o checkpoint sem interromper
o lote e sem reescrever arquivos. `resumo.json` é atualizado a cada 25 partes e ao
finalizar/parar.

## Resultados e revisão

- `apps.csv`: todos os apps, estados e cobertura por partes.
- `funcionalidades.csv`: nomes propostos, evidências, offsets, origem e hashes.
- `extractions.jsonl`: um registro por app, incluindo pendentes, vazios e erros.
- `taxonomia-para-revisao.csv`: nomes brutos e frequência por app. A igualdade de
  texto não é agrupamento semântico. Códigos normalizados ficam para revisão.
- `checkpoint.sqlite3`: partes, respostas brutas e histórico das tentativas.
- `run-manifest.json`: modelo/digest, versão Ollama, prompt, opções e hashes do código.
- `executions.jsonl`: parâmetros operacionais e término de cada execução.

Os CSVs dessa pasta são saídas automáticas e são atualizados durante a execução.
Enquanto houver partes pendentes ou com erro, uma candidata já exportada pode
pertencer a app parcialmente analisado. Confira `technical_complete` em apps.csv
e `app_complete` em funcionalidades.csv antes de usar contagens como finais.
Para registrar revisão sem sobrescrever trabalho humano, crie uma cópia separada:

```bash
python3 batch_tools/tea_batch.py review \
  --out analysis/lote-3141 --review-dir analysis/revisao-lote-3141
```

Esse comando exige pasta de revisão nova. Preencha `human_decision`,
`human_name_correction` e `human_reviewer` na cópia. As revisões não são importadas
automaticamente de volta ao checkpoint nem usadas para inventar métricas.

Não é necessário que uma pessoa extraia manualmente os 3.141 apps. A equipe deve
avaliar uma amostra independente para estimar erros e revisar a normalização/FODA.
Para os 60 apps já separados, mantenha as previsões ocultas dos anotadores até
terminarem a referência humana. Depois compare nomes por significado, não apenas
por igualdade textual. Esses controles não são substituídos por citação literal.

Os 100 apps analisados pelo ChatGPT anteriormente não são importados como saídas
do Ollama nem como padrão ouro. Para obter um corpus uniforme atribuído a um
modelo registrado, o lote extrai novamente suas descrições locais; isso não baixa
os apps nem consulta a Google Play.

## O que foi testado e o que ainda depende do servidor

Foram testados entrada real dos 3.141 apps, cobertura integral da segmentação,
retomada por parte, deduplicação entre grupos, IDs inválidos, respostas truncadas,
limite total de tempo, HTTP real com servidor simulado, concorrência, isolamento
de configurações, respostas vazias e proteção da revisão humana.

Não foi realizada aqui inferência com um modelo real nem acesso ao servidor da
UTFPR. Os testes de transporte usam respostas controladas e não medem acurácia
de LLM. A automação está implementada; desempenho e qualidade no servidor precisam
ser medidos no primeiro teste com o modelo real.

API usada: documentação oficial consultada em 05/11/2026:

- https://docs.ollama.com/api/chat
- https://docs.ollama.com/api/tags
- https://docs.ollama.com/api-reference/show-model-details
- https://docs.ollama.com/capabilities/structured-outputs

O padrão `format=json` evita o esquema de geração com repetições limitadas que
causou o erro de gramática anterior. A resposta ainda passa pela validação local.
