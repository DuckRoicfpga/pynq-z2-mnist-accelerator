// ============================================================================
//  TESTBENCH cho MLP Neural Network Accelerator
// ============================================================================
//
//  Testbench nay:
//    1. Khoi tao module mlp_accelerator
//    2. Nap anh test tu file .mem (tung chu so 0-9)
//    3. Ghi 784 pixel vao module qua giao dien pixel_wr
//    4. Kich hoat start, cho done
//    5. So sanh ket qua voi nhan mong doi (expected label)
//    6. Bao cao PASS/FAIL cho tung anh
//
//  Cach chay trong Vivado:
//    1. Tao project, them file rtl/mlp_accelerator.v va rtl/params.vh
//    2. Them testbench nay vao Simulation Sources
//    3. Copy tat ca file .mem vao thu muc simulation working directory
//       (thong thuong la <project>/<project>.sim/sim_1/behav/xsim/)
//    4. Chay Behavioral Simulation
//
//  Cach chay voi Icarus Verilog (mien phi):
//    iverilog -I ../rtl -o tb_mlp ../rtl/mlp_accelerator.v tb_mlp_accelerator.v
//    vvp tb_mlp
//
// ============================================================================

`timescale 1ns / 1ps
`include "params.vh"

module tb_mlp_accelerator;

    // ======================================================================
    //  TIN HIEU
    // ======================================================================
    reg         clk;
    reg         rst_n;
    reg  [ 9:0] pixel_addr;
    reg  [ 7:0] pixel_data;
    reg         pixel_wr;
    reg         start;
    wire [ 3:0] result;
    wire        done;
    wire [ 2:0] dbg_state;
    wire [ 1:0] dbg_layer;
    wire [ 7:0] dbg_neuron;

    // ======================================================================
    //  KHOI TAO MODULE DUOI TEST (DUT)
    // ======================================================================
    mlp_accelerator dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .pixel_addr (pixel_addr),
        .pixel_data (pixel_data),
        .pixel_wr   (pixel_wr),
        .start      (start),
        .result     (result),
        .done       (done),
        .dbg_state  (dbg_state),
        .dbg_layer  (dbg_layer),
        .dbg_neuron (dbg_neuron)
    );

    // ======================================================================
    //  TAO XUNG CLOCK 100MHz (chu ky 10ns)
    // ======================================================================
    initial clk = 0;
    always #5 clk = ~clk;   // 5ns high + 5ns low = 10ns period

    // ======================================================================
    //  BO NHO LUU ANH TEST
    // ======================================================================
    reg [7:0] test_image [0:`INPUT_SIZE-1];  // 784 pixel

    // ======================================================================
    //  BO DEM KET QUA
    // ======================================================================
    integer pass_count;
    integer fail_count;
    integer test_digit;
    integer i;

    // ======================================================================
    //  TASK: Ghi 784 pixel vao module
    // ======================================================================
    task write_image;
        begin
            for (i = 0; i < `INPUT_SIZE; i = i + 1) begin
                @(posedge clk);
                pixel_addr <= i;
                pixel_data <= test_image[i];
                pixel_wr   <= 1'b1;
            end
            @(posedge clk);
            pixel_wr <= 1'b0;
        end
    endtask

    // ======================================================================
    //  TASK: Bat dau suy luan va cho ket qua
    // ======================================================================
    task run_inference;
        begin
            @(posedge clk);
            start <= 1'b1;
            @(posedge clk);
            start <= 1'b0;

            // Cho tin hieu done (timeout sau 500,000 clock = 5ms @ 100MHz)
            fork
                begin
                    @(posedge done);
                end
                begin
                    repeat (500000) @(posedge clk);
                    $display("[ERROR] TIMEOUT! Suy luan khong hoan tat sau 500,000 clock.");
                    $finish;
                end
            join_any
            disable fork;
        end
    endtask

    // ======================================================================
    //  CHUONG TRINH TEST CHINH
    // ======================================================================
    initial begin
        // --- Khoi tao ---
        rst_n      = 1'b0;
        pixel_addr = 10'd0;
        pixel_data = 8'd0;
        pixel_wr   = 1'b0;
        start      = 1'b0;
        pass_count = 0;
        fail_count = 0;

        // --- Reset ---
        repeat (10) @(posedge clk);
        rst_n = 1'b1;
        repeat (5) @(posedge clk);

        $display("");
        $display("============================================================");
        $display("  TESTBENCH: MLP Neural Network Accelerator");
        $display("  Kien truc: %0d -> %0d -> %0d -> %0d",
                 `INPUT_SIZE, `L1_NEURONS, `L2_NEURONS, `L3_NEURONS);
        $display("  SHIFT1=%0d, SHIFT2=%0d", `SHIFT1, `SHIFT2);
        $display("============================================================");
        $display("");

        // --- Test tung chu so tu 0 den 9 ---
        for (test_digit = 0; test_digit < 10; test_digit = test_digit + 1) begin

            // Nap anh tu file .mem
            case (test_digit)
                0: $readmemh("test_image_0.mem", test_image);
                1: $readmemh("test_image_1.mem", test_image);
                2: $readmemh("test_image_2.mem", test_image);
                3: $readmemh("test_image_3.mem", test_image);
                4: $readmemh("test_image_4.mem", test_image);
                5: $readmemh("test_image_5.mem", test_image);
                6: $readmemh("test_image_6.mem", test_image);
                7: $readmemh("test_image_7.mem", test_image);
                8: $readmemh("test_image_8.mem", test_image);
                9: $readmemh("test_image_9.mem", test_image);
            endcase

            // Ghi pixel vao module
            write_image;

            // Chay suy luan
            $display("  [TEST %0d] Chu so = %0d | Dang suy luan...", test_digit, test_digit);
            run_inference;

            // Kiem tra ket qua
            if (result == test_digit) begin
                $display("           -> Ket qua = %0d | PASS (dung!)", result);
                pass_count = pass_count + 1;
            end else begin
                $display("           -> Ket qua = %0d | FAIL (sai, mong doi %0d)", result, test_digit);
                fail_count = fail_count + 1;
            end

            $display("");
            repeat (10) @(posedge clk);  // Delay giua cac test
        end

        // --- Bao cao tong ket ---
        $display("============================================================");
        $display("  KET QUA TONG KET");
        $display("============================================================");
        $display("  PASS: %0d / 10", pass_count);
        $display("  FAIL: %0d / 10", fail_count);
        if (fail_count == 0)
            $display("  >> TAT CA TEST PASS! Phan cung hoat dong chinh xac. <<");
        else
            $display("  >> CO %0d TEST FAIL. Kiem tra lai thiet ke. <<", fail_count);
        $display("============================================================");
        $display("");

        $finish;
    end

    // ======================================================================
    //  DUMP WAVEFORM (cho GTKWave hoac Vivado Waveform Viewer)
    // ======================================================================
    initial begin
        $dumpfile("tb_mlp_accelerator.vcd");
        $dumpvars(0, tb_mlp_accelerator);
    end

endmodule
