`timescale 1ns / 1ps
`include "params.vh"
`include "case_count.vh"

// Golden vectors are generated from the saved export by verify_stage1.py.
// Checks all layer values, MAC operands, repeated runs and reset during work.
module tb_mlp_regression;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg [9:0] pixel_addr = 0;
    reg [7:0] pixel_data = 0;
    reg pixel_wr = 0;
    reg start = 0;
    wire [3:0] result;
    wire done;
    wire [2:0] dbg_state;
    wire [1:0] dbg_layer;
    wire [7:0] dbg_neuron;

    mlp_accelerator dut (
        .clk(clk), .rst_n(rst_n), .pixel_addr(pixel_addr),
        .pixel_data(pixel_data), .pixel_wr(pixel_wr), .start(start),
        .result(result), .done(done), .dbg_state(dbg_state),
        .dbg_layer(dbg_layer), .dbg_neuron(dbg_neuron)
    );

    reg [7:0] inputs [0:`CASE_COUNT*`INPUT_SIZE-1];
    reg [7:0] expected_l1 [0:`CASE_COUNT*`L1_NEURONS-1];
    reg [7:0] expected_l2 [0:`CASE_COUNT*`L2_NEURONS-1];
    reg signed [31:0] expected_l3 [0:`CASE_COUNT*`L3_NEURONS-1];
    reg [7:0] expected_predictions [0:`CASE_COUNT-1];
    integer case_idx = 0;
    integer cycles, mac_ops = 0, i;
    integer total_values = 0;
    integer min_cycles = 2147483647, max_cycles = 0;
    integer audit_w_index;
    reg [7:0] audit_x;
    reg signed [7:0] audit_w;
    reg signed [16:0] audit_product;
    reg check_mac = 0;
    integer fd;

    // Sample before the clock's nonblocking assignments: these operands
    // are exactly the ones used by the accumulator at this edge.
    always @(posedge clk) begin
        if (rst_n && check_mac && dbg_state == 3'd4) begin
            if (dut.mac_count >= dut.num_inputs)
                $fatal(1, "MAC count outside neuron input range");
            case (dbg_layer)
                0: begin
                    audit_w_index = dbg_neuron*`INPUT_SIZE + dut.mac_count;
                    audit_w = dut.w1_mem[audit_w_index];
                    audit_x = inputs[case_idx*`INPUT_SIZE + dut.mac_count];
                end
                1: begin
                    audit_w_index = dbg_neuron*`L1_NEURONS + dut.mac_count;
                    audit_w = dut.w2_mem[audit_w_index];
                    audit_x = expected_l1[case_idx*`L1_NEURONS + dut.mac_count];
                end
                2: begin
                    audit_w_index = dbg_neuron*`L2_NEURONS + dut.mac_count;
                    audit_w = dut.w3_mem[audit_w_index];
                    audit_x = expected_l2[case_idx*`L2_NEURONS + dut.mac_count];
                end
                default: $fatal(1, "Invalid layer during MAC");
            endcase
            audit_product = audit_w * $signed({1'b0, audit_x});
            if (dut.product_reg !== audit_product)
                $fatal(1, "Pipelined MAC product mismatch case=%0d layer=%0d neuron=%0d input=%0d got=%0d expected=%0d",
                    case_idx, dbg_layer, dbg_neuron, dut.mac_count,
                    dut.product_reg, audit_product);
            if ($isunknown(dut.acc) || $isunknown(dut.product_reg))
                $fatal(1, "Unknown accumulator/product during MAC");
            mac_ops = mac_ops + 1;
        end
    end

    task load_image(input integer idx);
        integer p;
        begin
            for (p = 0; p < `INPUT_SIZE; p = p + 1) begin
                @(negedge clk);
                pixel_addr = p;
                pixel_data = inputs[idx*`INPUT_SIZE + p];
                pixel_wr = 1;
            end
            @(negedge clk);
            pixel_wr = 0;
        end
    endtask

    task launch;
        begin
            @(negedge clk);
            start = 1;
            @(negedge clk);
            start = 0;
        end
    endtask

    initial begin
        $readmemh("inputs.mem", inputs);
        $readmemh("expected_l1.mem", expected_l1);
        $readmemh("expected_l2.mem", expected_l2);
        $readmemh("expected_l3.mem", expected_l3);
        $readmemh("expected_predictions.mem", expected_predictions);
        fd = $fopen("rtl_results.csv", "w");
        if (!fd) $fatal(1, "Cannot write results CSV");
        $fdisplay(fd, "case,prediction,expected,cycles,mac_operations,layer_values_checked");
        repeat (5) @(negedge clk);
        rst_n = 1;

        // Abort one in-progress inference and verify a clean restart.
        load_image(0);
        launch;
        repeat (40) @(negedge clk);
        if (dbg_state == 0) $fatal(1, "DUT did not start before reset test");
        rst_n = 0;
        repeat (3) @(negedge clk);
        if (dbg_state !== 0 || done !== 0 || result !== 0)
            $fatal(1, "Reset did not clear control/result");
        rst_n = 1;
        $display("PASS: reset during active inference");

        for (case_idx = 0; case_idx < `CASE_COUNT; case_idx = case_idx + 1) begin
            load_image(case_idx);
            cycles = 0;
            mac_ops = 0;
            check_mac = 1;
            launch;
            while (done !== 1'b1 && cycles < 120000) begin
                @(posedge clk);
                #1;
                cycles = cycles + 1;
                // A start and a pixel write while busy must be ignored.
                if (case_idx == 0 && cycles == 20) begin
                    @(negedge clk);
                    start = 1;
                    pixel_addr = 0;
                    pixel_data = inputs[0] ^ 8'hFF;
                    pixel_wr = 1;
                end
                if (case_idx == 0 && cycles == 21) begin
                    @(negedge clk);
                    start = 0;
                    pixel_wr = 0;
                end
            end
            check_mac = 0;
            if (done !== 1'b1) $fatal(1, "Timeout case=%0d", case_idx);
            if (result !== expected_predictions[case_idx][3:0])
                $fatal(1, "Prediction mismatch case=%0d got=%0d expected=%0d",
                    case_idx, result, expected_predictions[case_idx]);
            if (mac_ops != `W1_DEPTH + `W2_DEPTH + `W3_DEPTH)
                $fatal(1, "Wrong number of MAC operations: %0d", mac_ops);
            for (i = 0; i < `L1_NEURONS; i = i + 1)
                if (dut.l1_out[i] !== expected_l1[case_idx*`L1_NEURONS + i])
                    $fatal(1, "Layer 1 mismatch case=%0d neuron=%0d", case_idx, i);
            for (i = 0; i < `L2_NEURONS; i = i + 1)
                if (dut.l2_out[i] !== expected_l2[case_idx*`L2_NEURONS + i])
                    $fatal(1, "Layer 2 mismatch case=%0d neuron=%0d", case_idx, i);
            for (i = 0; i < `L3_NEURONS; i = i + 1)
                if (dut.l3_out[i] !== expected_l3[case_idx*`L3_NEURONS + i])
                    $fatal(1, "Layer 3 mismatch case=%0d neuron=%0d got=%0d expected=%0d",
                        case_idx, i, dut.l3_out[i], expected_l3[case_idx*`L3_NEURONS + i]);
            if (case_idx == 0 && dut.input_mem[0] !== inputs[0])
                $fatal(1, "Busy pixel write corrupted input memory");
            total_values = total_values + `L1_NEURONS + `L2_NEURONS + `L3_NEURONS;
            if (cycles < min_cycles) min_cycles = cycles;
            if (cycles > max_cycles) max_cycles = cycles;
            $fdisplay(fd, "%0d,%0d,%0d,%0d,%0d,%0d", case_idx, result,
                expected_predictions[case_idx], cycles, mac_ops,
                `L1_NEURONS + `L2_NEURONS + `L3_NEURONS);
            if (case_idx < 10 || case_idx % 10 == 9 || case_idx >= `CASE_COUNT-10)
                $display("PASS case=%0d result=%0d cycles=%0d MACs=%0d", case_idx, result, cycles, mac_ops);
            @(posedge clk);
            #1;
            if (done !== 0 || dbg_state !== 0)
                $fatal(1, "Done must be a one-cycle pulse and return to IDLE");
        end
        $fclose(fd);
        $display("REGRESSION PASS: %0d/%0d cases, %0d layer values, cycles=%0d..%0d",
            `CASE_COUNT, `CASE_COUNT, total_values, min_cycles, max_cycles);
        $finish;
    end
endmodule
