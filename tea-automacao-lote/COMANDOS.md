# Classificação e extração dos 3.141 apps

Esta versão usa Python 3.10+ e Ollama local. Não precisa de venv, pip, npm,
assinatura de API ou coleta adicional da Google Play. Não baixa modelos.

O fluxo é feito em duas etapas sequenciais para cada app:

1. **Classificação LLM:** lê o título e a descrição completa dos 3.141 apps,
   sem pré-filtro lexical. Decide `relevant`, `not_relevant` ou `uncertain`.
2. **Extração LLM:** somente apps `relevant` seguem para extração das
   funcionalidades por partes.

`relevant` significa que o app apresenta pessoas neurodivergentes como público-alvo
ou descreve suporte direcionado como finalidade/recurso central. Menção incidental
(por exemplo, um teste de TDAH entre muitos testes de um app geral de bem-estar)
deve ser `not_relevant`. Casos que a descrição não permite decidir ficam
`uncertain`, para revisão; não são extraídos nem descartados silenciosamente.
Grupos de busca servem apenas como proveniência e não são enviados como evidência.

A classificação e as funcionalidades são previsões do modelo, não verdade de
referência. O Python valida formato e se a evidência citada é literal, mas isso
não prova que a justificativa esteja semanticamente correta. Revise uma amostra,
incluindo `uncertain` e `not_relevant`, antes de usar os resultados como dados
finais. Cada classificação e sua citação ficam registradas no SQLite, `apps.csv`
e `extractions.jsonl`; as tentativas brutas ficam no checkpoint.

## Aplicar e testar o código

Baixe e extraia o ZIP antes dos comandos. No repositório em que você já trabalha:

```bash
unzip ~/Downloads/tea-automacao-lote.zip -d ~/Downloads &&
cd ~/Documentos/github/eng-soft-empirica/tea-scrapper &&
bash ~/Downloads/tea-automacao-lote/aplicar.sh &&
python3 -m unittest discover -s batch_tools -p 'test_*.py' -v
```

O aplicador verifica os arquivos do pacote, aceita reaplicação idêntica, atualiza
somente os arquivos da versão anterior se seus hashes ainda forem exatamente os
esperados e recusa qualquer outra colisão. Não usa reset, checkout, clean ou
aplicação forçada.

Se estiver no servidor e o repositório tiver outro endereço, entre nele primeiro
e execute os mesmos comandos a partir de `bash .../aplicar.sh`. Copie o pacote e
os JSONs para o servidor ou use o repositório que o Pedro já possui lá. O caminho
local da sua máquina não existe automaticamente no servidor.

## Preparar todos os apps, sem chamar a IA

Na raiz do repositório:

```bash
python3 batch_tools/tea_batch.py prepare \
  --results output/results_2026-10-19 \
  --out analysis/lote-3141-v3 \
  --expect-apps 3141

python3 batch_tools/tea_batch.py plan --out analysis/lote-3141-v3
```

Use uma pasta nova. `lote-3141-v2` contém o filtro lexical antigo e seus
checkpoints não são compatíveis com esta versão. O planejamento estima chamadas
de classificação para todos os apps e partes de extração se todos forem relevantes;
não faz chamadas ao modelo. Na coleta atual, são 3.141 classificações e até 5.122
partes de extração se todos forem relevantes. `--expect-apps 3141` evita executar
uma coleta diferente.

## Primeiro teste com o modelo real no servidor

Veja `ollama list` na máquina que executará a extração. A coleta anterior usou
`qwen3.6-35b-cpu:latest`; o modelo precisa estar instalado na máquina local ou no
servidor. Troque o nome se estiver usando outro modelo e faça isso antes da
primeira geração desta pasta.

```bash
python3 batch_tools/tea_batch.py doctor --model qwen3.6-35b-cpu:latest

python3 batch_tools/tea_batch.py run \
  --out analysis/lote-3141-v3 --model qwen3.6-35b-cpu:latest \
  --app-id uk.co.mymolehillmountain.autistica \
  --app-id com.dmwaresolutions.meuabinha \
  --app-id aba.picture.deck

python3 batch_tools/tea_batch.py status --out analysis/lote-3141-v3
```

Cada app selecionado passa primeiro pela classificação. Só os rotulados
`relevant` são enviados à extração; `uncertain` fica para revisão e
`not_relevant` não é extraído. `apps.csv` registra decisão, justificativa, citação
e estado. `--app-id` restringe o teste sem impedir a retomada do restante depois.

Inspecione os três resultados em `apps.csv` e `funcionalidades.csv`; confirme
especialmente que uma menção incidental não é classificada como relevante e que
uma descrição sem menção literal mas com suporte direcionado não é descartada.
Esse teste inicial não mede acurácia representativa.

## Executar a classificação e extração

Uma execução completa classifica todos os apps ainda pendentes e extrai os que o
modelo classificar como relevantes:

```bash
python3 batch_tools/tea_batch.py run \
  --out analysis/lote-3141-v3 --model qwen3.6-35b-cpu:latest --retry-errors
```

O mesmo comando retoma classificação e extração sem repetir resultados salvos.
Ctrl+C encerra o agendamento e preserva o checkpoint; depois repita o comando.
Uma classificação bem-sucedida também fica salva, inclusive quando a extração
posterior falha.

O padrão usa um worker para não multiplicar a demanda de memória e a fila do
modelo. `--workers 2` permite duas chamadas em paralelo, mas só vale aumentar se
o servidor suportar e a medição mostrar ganho. Workers, timeout e seleção de
apps podem mudar ao retomar. Modelo, digest, versão, prompt, código ou opções de
geração diferentes exigem uma nova pasta preparada com os mesmos JSONs.

Retentativas são limitadas: no máximo duas chamadas por classificação ou parte
por execução. Um timeout não é repetido automaticamente e interrompe o
agendamento. `--retry-errors` autoriza tentar erros anteriores outra vez;
sucessos não são repetidos. HTTP 400/401/403/404 interrompe novo agendamento.
Três falhas seguidas de transporte também interrompem o lote.
Leia o erro e corrija a causa antes de repetir indefinidamente.

Para deixar o processo rodando mesmo após encerrar a sessão SSH, opcionalmente:

```bash
nohup python3 batch_tools/tea_batch.py run \
  --out analysis/lote-3141-v3 --model qwen3.6-35b-cpu:latest --retry-errors \
  > analysis/lote-3141-v3/execucao.log 2>&1 &
```

Não inicie outra geração na mesma pasta enquanto essa estiver ativa. O lock impede
dois escritores. Nesse caso, acompanhe `tail -n 20 analysis/lote-3141-v3/execucao.log`
ou use `status --out analysis/lote-3141-v3`, que consulta o checkpoint sem interromper
o lote e sem reescrever arquivos. `resumo.json` é atualizado a cada 25 respostas e ao
finalizar/parar.

## Resultados e revisão

- `apps.csv`: todos os apps, decisão de relevância, justificativa, evidência e estado.
- `funcionalidades.csv`: nomes propostos, evidências, offsets, origem e hashes.
- `extractions.jsonl`: um registro por app, incluindo pendentes, vazios e erros.
- `taxonomia-para-revisao.csv`: nomes brutos e frequência por app. A igualdade de
  texto não é agrupamento semântico. Códigos normalizados ficam para revisão.
- `checkpoint.sqlite3`: classificações, partes, respostas brutas e histórico das tentativas.
- `run-manifest.json`: modelo/digest, versão Ollama, prompt, opções e hashes do código.
- `executions.jsonl`: parâmetros operacionais e término de cada execução.

Os CSVs dessa pasta são saídas automáticas e são atualizados durante a execução.
Enquanto houver classificações ou partes pendentes/com erro, uma candidata já
exportada pode pertencer a app parcialmente analisado. Confira `technical_complete`
em apps.csv e `app_complete` em funcionalidades.csv. Revise também os casos
`needs_relevance_review` e a amostra dos `classified_not_relevant`.
Para registrar revisão sem sobrescrever trabalho humano, crie uma cópia separada:

```bash
python3 batch_tools/tea_batch.py review \
  --out analysis/lote-3141-v3 --review-dir analysis/revisao-lote-3141-v3
```

Esse comando exige pasta de revisão nova. Em `apps.csv`, preencha
`relevance_human_decision` e `relevance_human_reviewer`; em
`funcionalidades.csv`, preencha `human_decision`, `human_name_correction` e
`human_reviewer`. As revisões não são importadas automaticamente para o checkpoint.

Não é necessário que uma pessoa revise os 3.141 apps um a um. Avalie amostras
independentes de cada decisão de relevância e de funcionalidades; preserve rótulos
humanos como referência independente. A citação literal não substitui essa revisão.

Os 100 apps analisados pelo ChatGPT anteriormente não são importados como saídas
do Ollama nem como padrão ouro. Para obter um corpus uniforme atribuído a um
modelo registrado, o lote extrai novamente suas descrições locais; isso não baixa
os apps nem consulta a Google Play.

## O que foi testado e o que ainda depende do servidor

Foram testados classificação seguida de extração, bloqueio da extração para
`not_relevant`/`uncertain`, validação de evidência literal, retomada de cada etapa,
entrada real dos 3.141 apps, cobertura integral da segmentação, IDs inválidos,
respostas truncadas, timeout, HTTP simulado, concorrência e proteção da revisão.

Não houve inferência com modelo real nem acesso ao servidor UTFPR neste ambiente.
Os testes usam classificações/respostas simuladas e não medem precisão ou recall.
Valide as categorias com uma amostra humana antes de tirar conclusões.

API usada: documentação oficial consultada em 05/11/2026:

- https://docs.ollama.com/api/chat
- https://docs.ollama.com/api/tags
- https://docs.ollama.com/api-reference/show-model-details
- https://docs.ollama.com/capabilities/structured-outputs

O padrão `format=json` evita o esquema de geração com repetições limitadas que
causou o erro de gramática anterior. A resposta ainda passa pela validação local.
