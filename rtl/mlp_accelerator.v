// ============================================================================
//  MLP Neural Network Accelerator for FPGA (PYNQ-Z2 / Zynq-7020)
// ============================================================================
//
//  Module nay thuc hien SUY LUAN (inference) mang MLP tren phan cung FPGA.
//  Kien truc mang: 784 -> 128 (ReLU) -> 64 (ReLU) -> 10 (argmax)
//
//  Nguyen ly hoat dong:
//  --------------------
//  1. CPU (hoac testbench) ghi 784 pixel anh vao input_mem qua giao dien ghi
//  2. Kich hoat tin hieu 'start'
//  3. FSM dieu khien tinh toan tuan tu qua 3 layer:
//     - Moi neuron: doc trong so tu BRAM, nhan voi input, cong don (MAC)
//     - Cong bias (da pre-scale thanh INT32)
//     - Ap dung ReLU + Right-Shift + Clip (cho hidden layer)
//  4. Tim argmax cua 10 dau ra -> ket qua la chu so 0-9
//  5. Bao hieu 'done', ket qua tren 'result'
//
//  Pipeline:
//  ---------
//  BRAM co 1 chu ky tre (synchronous read):
//    Cycle 0: Dat dia chi   -> BRAM doc du lieu
//    Cycle 1: Du lieu san sang -> Thuc hien MAC
//  Ket qua phep nhan duoc dang ky them 1 clock de tach duong BRAM -> MAC.
//  Sau khi pipeline day, dat duoc 1 MAC/clock.
//
//  Reset dong bo, active-low. CLK va rst_n phai cung clock domain.
//  Trong so ROM duoc nap san trong bitstream tu cac file .mem.
//  Xem output/stage3 de biet tai nguyen va timing sau implementation.
//
// ============================================================================

`timescale 1ns / 1ps
`include "params.vh"

module mlp_accelerator (
    input  wire        clk,        // Clock (100 MHz tren PYNQ-Z2)
    input  wire        rst_n,      // Reset tich cuc muc thap (active-low)

    // --- Giao dien ghi pixel dau vao ---
    input  wire [ 9:0] pixel_addr, // Dia chi pixel (0 den 783)
    input  wire [ 7:0] pixel_data, // Gia tri pixel (0 den 255, grayscale)
    input  wire        pixel_wr,   // Tin hieu ghi (write enable)

    // --- Dieu khien ---
    input  wire        start,      // Xung bat dau suy luan

    // --- Ket qua ---
    output reg  [ 3:0] result,     // Chu so du doan (0-9)
    output reg         done,       // Bao hieu hoan tat

    // --- Debug (tuy chon, noi vao LED hoac ILA) ---
    output wire [ 2:0] dbg_state,
    output wire [ 1:0] dbg_layer,
    output wire [ 7:0] dbg_neuron
);

    // ======================================================================
    //  KHAI BAO TRANG THAI FSM
    // ======================================================================
    localparam S_IDLE    = 3'd0;   // Cho lenh start
    localparam S_INIT    = 3'd1;   // Khoi tao tham so cho layer hien tai
    localparam S_ADDR    = 3'd2;   // Dat dia chi BRAM dau tien cho neuron moi
    localparam S_WAIT    = 3'd3;   // Cho 1 clock de BRAM tra du lieu
    localparam S_MAC     = 3'd4;   // Nhan-Cong don (1 MAC/clock)
    localparam S_BIAS    = 3'd5;   // Cong bias vao accumulator
    localparam S_STORE   = 3'd6;   // ReLU + Shift + Clip + Luu ket qua
    localparam S_ARGMAX  = 3'd7;   // Tim gia tri lon nhat trong 10 output

    reg [2:0] state;

    // ======================================================================
    //  THANH GHI DIEU KHIEN
    // ======================================================================
    reg [ 1:0] current_layer;      // Layer hien tai (0, 1, 2)
    reg [ 7:0] neuron_idx;         // Chi so neuron dang tinh (0-127)
    reg [ 9:0] mac_count;          // Dem so phep MAC da thuc hien trong neuron
    reg [ 9:0] num_inputs;         // So dau vao cua layer hien tai
    reg [ 7:0] num_neurons;        // So neuron cua layer hien tai
    reg [ 4:0] shift_amount;       // So bit dich phai (SHIFT1 hoac SHIFT2)
    reg        pipeline_wait;     // Them 1 clock de nap thanh ghi phep nhan

    // ======================================================================
    //  MAC ACCUMULATOR
    // ======================================================================
    reg signed [31:0] acc;         // Bo cong don 32-bit (signed)

    // Dia chi bo nho
    reg [16:0] w_addr;             // Dia chi trong so (dem tuan tu, toi da 100,352)
    reg [ 9:0] x_addr;             // Dia chi input (0 den 783, reset moi neuron)

    // Du lieu doc tu BRAM (1 chu ky tre)
    reg signed [ 7:0] w_rdata;     // Trong so doc duoc (INT8 signed)
    reg signed [ 7:0] w1_rdata, w2_rdata, w3_rdata;
    reg        [ 1:0] w_layer_d;   // Layer ung voi dia chi duoc doc o clock truoc
    reg        [ 7:0] x_rdata;     // Input doc duoc (UINT8)
    reg signed [31:0] bias_rdata;  // Bias doc duoc (INT32 signed)

    // Phep nhan: signed 8-bit x unsigned 8-bit
    // Mo rong unsigned thanh signed 9-bit (them bit 0 o MSB)
    wire signed [ 8:0] x_signed = {1'b0, x_rdata};
    (* use_dsp = "yes" *) wire signed [16:0] product = w_rdata * x_signed;
    reg signed [16:0] product_reg;
    always @(posedge clk) begin
        product_reg <= product;
    end

    // ======================================================================
    //  BO NHO (BRAM) - TRONG SO VA BIAS
    // ======================================================================
    //  Vivado se tu dong suy ra (infer) cac mang nay thanh Block RAM.
    //  Khoi tao bang $readmemh doc file .mem tu Python export.

    // --- Trong so (INT8 signed) ---
    (* rom_style = "block" *) reg [7:0] w1_mem [0:`W1_DEPTH-1];  // 128x784 = 100,352
    (* rom_style = "block" *) reg [7:0] w2_mem [0:`W2_DEPTH-1];  // 64x128  = 8,192
    (* rom_style = "block" *) reg [7:0] w3_mem [0:`W3_DEPTH-1];  // 10x64   = 640

    // --- Bias (INT32 signed, da pre-scale) ---
    reg signed [31:0] b1_mem [0:`L1_NEURONS-1];  // 128 entries
    reg signed [31:0] b2_mem [0:`L2_NEURONS-1];  // 64 entries
    reg signed [31:0] b3_mem [0:`L3_NEURONS-1];  // 10 entries

    // --- Bo nho dau vao va trung gian ---
    reg [7:0] input_mem [0:`INPUT_SIZE-1];   // 784 pixel dau vao
    reg [7:0] l1_out    [0:`L1_NEURONS-1];   // 128 output Layer 1 (8-bit)
    reg [7:0] l2_out    [0:`L2_NEURONS-1];   // 64 output Layer 2 (8-bit)
    reg signed [31:0] l3_out [0:`L3_NEURONS-1]; // 10 output Layer 3 (32-bit raw)

    // ======================================================================
    //  KHOI TAO BO NHO TU FILE .mem (cho ca simulation va synthesis)
    // ======================================================================
    initial begin
        $readmemh("fc1_weight.mem", w1_mem);
        $readmemh("fc2_weight.mem", w2_mem);
        $readmemh("fc3_weight.mem", w3_mem);
        $readmemh("fc1_bias.mem",   b1_mem);
        $readmemh("fc2_bias.mem",   b2_mem);
        $readmemh("fc3_bias.mem",   b3_mem);
    end

    // ======================================================================
    //  DOC BRAM DONG BO (Synchronous Read)
    // ======================================================================
    //  Moi chu ky clock, BRAM doc du lieu tai dia chi hien tai.
    //  Du lieu san sang o chu ky TIEP THEO (1-cycle latency).

    // Moi ROM co thanh ghi doc rieng de Vivado infer Block ROM.
    // Mux dat SAU thanh ghi; w_layer_d giu dung do tre 1 clock
    // cua ca du lieu va tin hieu chon layer.
    always @(posedge clk) begin
        w_layer_d <= current_layer;
        case (current_layer)
            2'd0: w1_rdata <= $signed(w1_mem[w_addr]);
            2'd1: w2_rdata <= $signed(w2_mem[w_addr]);
            2'd2: w3_rdata <= $signed(w3_mem[w_addr]);
            default: ;
        endcase
    end

    always @(*) begin
        case (w_layer_d)
            2'd0: w_rdata = w1_rdata;
            2'd1: w_rdata = w2_rdata;
            2'd2: w_rdata = w3_rdata;
            default: w_rdata = 8'sd0;
        endcase
    end

    // Doc input: chon nguon du lieu theo layer hien tai
    always @(posedge clk) begin
        case (current_layer)
            2'd0: x_rdata <= input_mem[x_addr];
            2'd1: x_rdata <= l1_out[x_addr];
            2'd2: x_rdata <= l2_out[x_addr];
            default: x_rdata <= 8'd0;
        endcase
    end

    // Doc bias: doc theo neuron_idx va layer
    always @(posedge clk) begin
        case (current_layer)
            2'd0: bias_rdata <= b1_mem[neuron_idx];
            2'd1: bias_rdata <= b2_mem[neuron_idx];
            2'd2: bias_rdata <= b3_mem[neuron_idx];
            default: bias_rdata <= 32'sd0;
        endcase
    end

    // ======================================================================
    //  GIAO DIEN GHI PIXEL DAU VAO
    // ======================================================================
    //  CPU/testbench ghi pixel vao input_mem khi module o trang thai IDLE.
    always @(posedge clk) begin
        if (rst_n && pixel_wr && state == S_IDLE && pixel_addr < `INPUT_SIZE) begin
            input_mem[pixel_addr] <= pixel_data;
        end
    end

    // ======================================================================
    //  ReLU + RIGHT-SHIFT + CLIP (to hop)
    // ======================================================================
    //  Tinh toan ket qua 8-bit tu accumulator 32-bit.
    //  ReLU: neu am thi = 0
    //  Shift: dich phai de giam bit-width
    //  Clip: gioi han trong [0, 255]
    wire [31:0] relu_val   = acc[31] ? 32'd0 : acc;  // ReLU: MSB=1 la am -> 0
    wire [31:0] shifted    = relu_val >> shift_amount; // Right-shift
    wire [ 7:0] clipped    = (shifted > 32'd255) ? 8'd255 : shifted[7:0]; // Clip

    // Ghi bo nho dong bo, tach khoi FSM co reset bat dong bo.
    // Khong reset noi dung RAM: moi lan suy luan ghi de tat ca neuron
    // truoc khi layer tiep theo doc. rst_n chi cho phep ghi tai clock edge.
    always @(posedge clk) begin
        if (rst_n && state == S_STORE) begin
            if (current_layer == 2'd2)
                l3_out[neuron_idx] <= acc;
            else if (current_layer == 2'd0)
                l1_out[neuron_idx] <= clipped;
            else
                l2_out[neuron_idx] <= clipped;
        end
    end

    // ======================================================================
    //  ARGMAX
    // ======================================================================
    reg signed [31:0] max_val;     // Gia tri lon nhat hien tai
    reg [ 3:0] max_idx;            // Chi so cua gia tri lon nhat
    reg [ 3:0] argmax_cnt;         // Bo dem argmax (0-10)

    // ======================================================================
    //  MAY TRANG THAI HUU HAN (FSM) CHINH
    // ======================================================================
    always @(posedge clk) begin
        if (!rst_n) begin
            // ---- RESET ----
            state         <= S_IDLE;
            current_layer <= 2'd0;
            neuron_idx    <= 8'd0;
            mac_count     <= 10'd0;
            acc           <= 32'sd0;
            w_addr        <= 17'd0;
            x_addr        <= 10'd0;
            num_inputs    <= 10'd0;
            num_neurons   <= 8'd0;
            shift_amount  <= 5'd0;
            result        <= 4'd0;
            done          <= 1'b0;
            max_val       <= 32'sd0;
            max_idx       <= 4'd0;
            argmax_cnt    <= 4'd0;
            pipeline_wait <= 1'b0;
        end else begin
            // Mac dinh: done chi bao 1 clock
            done <= 1'b0;

            case (state)

                // ==============================================================
                //  IDLE: Cho tin hieu start
                // ==============================================================
                S_IDLE: begin
                    if (start) begin
                        current_layer <= 2'd0;
                        state         <= S_INIT;
                    end
                end

                // ==============================================================
                //  INIT: Thiet lap tham so cho layer hien tai
                // ==============================================================
                S_INIT: begin
                    neuron_idx <= 8'd0;
                    w_addr     <= 17'd0;

                    case (current_layer)
                        2'd0: begin
                            num_inputs   <= `INPUT_SIZE;  // 784
                            num_neurons  <= `L1_NEURONS;  // 128
                            shift_amount <= `SHIFT1;
                        end
                        2'd1: begin
                            num_inputs   <= `L1_NEURONS;  // 128
                            num_neurons  <= `L2_NEURONS;  // 64
                            shift_amount <= `SHIFT2;
                        end
                        2'd2: begin
                            num_inputs   <= `L2_NEURONS;  // 64
                            num_neurons  <= `L3_NEURONS;  // 10
                            shift_amount <= 5'd0;         // Khong shift o output layer
                        end
                        default: ;
                    endcase

                    state <= S_ADDR;
                end

                // ==============================================================
                //  ADDR: Dat dia chi BRAM dau tien cho neuron moi
                // ==============================================================
                //  - Reset x_addr ve 0 (bat dau doc input tu dau)
                //  - w_addr tiep tuc tu vi tri truoc (tuan tu qua cac neuron)
                //  - Xoa accumulator
                S_ADDR: begin
                    x_addr    <= 10'd0;
                    acc       <= 32'sd0;
                    mac_count <= 10'd0;
                    pipeline_wait <= 1'b0;
                    state     <= S_WAIT;
                    // w_addr giu nguyen (da dat trong S_INIT hoac tu neuron truoc)
                    // BRAM se doc w_mem[w_addr] va input[0] tai clock edge nay
                end

                // ==============================================================
                //  WAIT: Cho 1 clock de BRAM tra du lieu
                // ==============================================================
                //  Dong thoi dat dia chi tiep theo (pipeline).
                //  Sau chu ky nay, w_rdata va x_rdata co du lieu cua dia chi
                //  da dat trong S_ADDR.
                S_WAIT: begin
                    x_addr <= x_addr + 10'd1;
                    w_addr <= w_addr + 17'd1;
                    if (pipeline_wait) begin
                        state <= S_MAC;
                    end else begin
                        pipeline_wait <= 1'b1;
                    end
                end

                // ==============================================================
                //  MAC: Nhan-Cong don (Multiply-Accumulate)
                // ==============================================================
                //  Moi clock thuc hien 1 phep MAC:
                //    acc += weight[n][i] * input[i]
                //
                //  Dong thoi dat dia chi cho phep doc tiep theo (pipelined).
                //  Nho vay dat 1 MAC/clock sau khi da khoi dong pipeline.
                S_MAC: begin
                    // --- Thuc hien MAC ---
                    // w_rdata va x_rdata la du lieu tu dia chi dat 2 clock truoc
                    acc <= acc + {{15{product_reg[16]}}, product_reg};

                    // --- Kiem tra hoan tat ---
                    if (mac_count == num_inputs - 10'd1) begin
                        // Da MAC het tat ca input cho neuron nay
                        state <= S_BIAS;
                    end else if (mac_count < num_inputs - 10'd2) begin
                        // Chuan bi dia chi tiep theo
                        x_addr <= x_addr + 10'd1;
                        w_addr <= w_addr + 17'd1;
                    end

                    mac_count <= mac_count + 10'd1;
                end

                // ==============================================================
                //  BIAS: Cong bias (INT32 pre-scaled) vao accumulator
                // ==============================================================
                //  bias_rdata da duoc doc dong bo tu BRAM bias tai moi clock
                //  (dua tren neuron_idx va current_layer).
                //  Vi neuron_idx khong doi tu S_ADDR den day, bias_rdata la dung.
                S_BIAS: begin
                    acc   <= acc + bias_rdata;
                    state <= S_STORE;
                end

                // ==============================================================
                //  STORE: ReLU + Shift + Clip + Luu ket qua
                // ==============================================================
                S_STORE: begin
                    // Block ghi RAM dong bo luu ket qua tai cung clock edge.

                    // --- Chuyen sang neuron tiep theo hoac layer tiep ---
                    if (neuron_idx == num_neurons - 8'd1) begin
                        // Het tat ca neuron trong layer nay
                        if (current_layer == 2'd2) begin
                            // Layer cuoi: chuyen sang ARGMAX
                            argmax_cnt <= 4'd0;
                            state      <= S_ARGMAX;
                        end else begin
                            // Con layer tiep theo
                            current_layer <= current_layer + 2'd1;
                            state         <= S_INIT;
                        end
                    end else begin
                        // Con neuron tiep theo trong layer nay
                        neuron_idx <= neuron_idx + 8'd1;
                        // w_addr da o vi tri dung cho neuron tiep theo
                        // (tang 2 lan trong S_WAIT va num_inputs-2 lan trong S_MAC)
                        state <= S_ADDR;
                    end
                end

                // ==============================================================
                //  ARGMAX: Tim chu so co diem cao nhat trong 10 output
                // ==============================================================
                //  Duyet qua l3_out[0..9], tim index co gia tri lon nhat.
                //  Su dung doc to hop (combinational read) vi l3_out chi co 10 phan tu.
                S_ARGMAX: begin
                    if (argmax_cnt < 4'd10) begin
                        if (argmax_cnt == 4'd0) begin
                            // Khoi tao voi phan tu dau tien
                            max_val <= l3_out[0];
                            max_idx <= 4'd0;
                        end else begin
                            // So sanh voi max hien tai
                            if (l3_out[argmax_cnt] > max_val) begin
                                max_val <= l3_out[argmax_cnt];
                                max_idx <= argmax_cnt;
                            end
                        end
                        argmax_cnt <= argmax_cnt + 4'd1;
                    end else begin
                        // Da duyet het 10 phan tu
                        result <= max_idx;
                        done   <= 1'b1;
                        state  <= S_IDLE;
                    end
                end

                default: state <= S_IDLE;

            endcase
        end
    end

    // ======================================================================
    //  TIN HIEU DEBUG
    // ======================================================================
    assign dbg_state  = state;
    assign dbg_layer  = current_layer;
    assign dbg_neuron = neuron_idx;

endmodule
