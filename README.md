# PROJETO DE ENCERRAMENTO DE RESIDÊNCIA
### DISPOSITIVO IoT PARA MONITORAMENTO DE SERVIDOR E INFRAESTRUTURA DE REDE

## 1. O Problema 

Sou Gerente de Infraestrutura de Redes em um provedor de internet. Atualmente, gerenciamos diversas salas de servidores e racks de distribuição espalhados pela cidade. Nosso maior problema é a falta de visibilidade em tempo real do que acontece dentro desses gabinetes fechados e o custo operacional e logístico de deslocar um técnico de plantão apenas para puxar o servidor da tomada quando ele trava e para de responder à rede.

Precisamos de uma solução embarcada e conectada (IoT) instalada em cada rack de TI. Esse dispositivo deve medir constantemente a temperatura e a umidade interna do gabinete, exibindo essas informações localmente para os técnicos de campo em um display. Além disso, os dados precisam ir para um painel centralizado (Dashboard) via internet para monitoramento remoto preventivo.

O ponto crítico e estratégico de atuação possui dois requisitos de controle:

* **Operação de Reset Hard:** Se um servidor travar, preciso conseguir enviar um comando remoto pela Dashboard para que o dispositivo acione um relé, interrompendo temporariamente a alimentação elétrica da máquina e restabelecendo-a em seguida para forçar a reinicialização do sistema.
* **Auditoria Visual Automatizada:** Antes ou após aplicar o comando de reset, o operador deve ser capaz de enviar um comando para que o dispositivo capture uma imagem do rack físico através de uma câmera integrada e a transmita para o servidor. Isso nos permitirá confirmar visualmente o status dos LEDs indicativos do servidor e checar a integridade física do rack sem o envio de uma equipe local.

## 2. Recomendações de Firmware e Conectividade

* **Conectividade e Telemetria de Clima:** O sistema deve se conectar de forma estável à rede local (Wi-Fi) e transmitir periodicamente (ex: a cada 10-30 segundos) as leituras dos sensores de temperatura e umidade para um servidor de nuvem/broker, alimentando os gráficos da Dashboard.
* **Comunicação Bidirecional e Assíncrona:** O firmware deve ser capaz de publicar dados de sensores e, concorrentemente, escutar comandos do servidor de forma assíncrona utilizando protocolos de comunicação IoT dedicados (como MQTT, HTTP REST com Long Polling ou WebSockets).
* **Interface Local (Display):** Atualizar constantemente o display do dispositivo com os valores atuais de temperatura, umidade e o status da conexão de rede para facilidade de diagnóstico em manutenções locais feitas por técnicos de campo.
* **Lógica de Temporização do Relé (Reset):** Ao receber o comando específico de "Reset" vindo da Dashboard, o firmware deve acionar o relé para interromper a alimentação do servidor, mantê-lo desligado por um curto período de segurança (ex: 3 a 5 segundos) e, em seguida, restabelecer a alimentação.
* **Acionamento da Câmera e Otimização de Mídia:** Ao receber o comando de captura vindo da Dashboard, o firmware deve registrar a imagem através da câmera integrada (resolução sugerida: VGA ou QVGA) e transmiti-la para o servidor/painel de forma eficiente, evitando estourar o buffer de memória RAM do microcontrolador.

## 3. Requisitos de Modelagem 3D 

O modelo 3D deste gabinete exige cuidados mecânicos específicos para o ambiente industrial:

* **Janelas de Interface e Visualização:** O case deve conter aberturas perfeitamente alinhadas para:
    * A tela do display (permitindo leitura rápida sem a necessidade de abrir o gabinete do dispositivo).
    * Abertura funcional e desimpedida para a lente da câmera.
* **Circulação de Ar Externa:** Desenhar fendas de ventilação posicionadas estrategicamente para que os sensores de temperatura e umidade recebam o ar real do rack de servidores e não sofram interferência ou falsa elevação de leitura pelo calor gerado pelos próprios componentes internos da placa (como o ESP32-S3 em processamento ou o acionamento do relé).
* **Acessos de Cabeamento e Fixação:** Prever furos passadores para o cabeamento de alimentação e para os fios de alta potência do relé. O case deve conter abas ou ganchos para fixação magnética ou por parafusos nas laterais internas do rack de TI.

## 4. Entregável Inicial: Documento de Arquitetura e Viabilidade Técnica

Antes de iniciar o desenvolvimento prático do firmware ou a modelagem 3D do gabinete, a equipe deverá entregar um relatório técnico de arquitetura contendo obrigatoriamente:

* **4.1. Mapeamento de Hardware e Componentes:** A equipe deve identificar e documentar os recursos integrados que serão ativados:
    * **Identificação:** Modelos exatos do sensor de temperatura/umidade, do display, do relé e do módulo de câmera presentes na placa educacional.
    * **Pinout (Tabela de GPIOs):** Tabela detalhada mapeando as conexões físicas de cada um desses periféricos com os pinos de entrada e saída do microcontrolador ESP32-S3.
    * **Barramentos Internos:** Indicação das interfaces de comunicação (ex: I2C para o display, barramento digital para sensores, barramento de câmera digital paralelo) que serão configuradas no código.

* **4.2. Diagrama de Blocos do Sistema:** Apresentar um esquema gráfico modular do hardware. No centro deve figurar o microcontrolador ESP32-S3 e, ao redor, blocos conectados por setas indicando o fluxo de sinal:
    * **Setas de entrada (In):** Sensores de temperatura/umidade e Câmera apontando para o ESP32-S3.
    * **Setas de saída (Out):** ESP32-S3 direcionadas ao Display e ao Relé.
    * **Fluxo de rede:** Seta representando a comunicação sem fio bidirecional trocando dados de telemetria e recebendo comandos do ecossistema de Nuvem/Dashboard.

* **4.3. Especificação do Protocolo de Comunicação e IoT:**
    * **Protocolo de Aplicação:** Escolha e justificativa do protocolo de comunicação de rede (ex: MQTT por permitir arquitetura pub/sub leve para comandos síncronos).
    * **Modelagem de Dados (Payloads):** Exemplo em formato de texto estruturado (JSON) demonstrando como as leituras de temperatura/umidade serão empacotadas para envio e como os comandos de Reset e Captura de Imagem serão estruturados pelo servidor.
    * **Arquitetura de Nuvem/Dashboard:** Descrição de qual plataforma ou ferramenta será adotada para hospedar o painel de monitoramento e controle do operador.
