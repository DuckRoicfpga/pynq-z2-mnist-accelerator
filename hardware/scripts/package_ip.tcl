set script_dir [file dirname [file normalize [info script]]]
set root_dir [file dirname [file dirname $script_dir]]
set hw_dir [file join $root_dir hardware]
set ip_dir [file join $hw_dir ip_repo mlp_axi_lite_1_0]
file mkdir $ip_dir
create_project -force mlp_ip_pack [file join $hw_dir build ip_pack] -part xc7z020clg400-1
set_property target_language Verilog [current_project]
add_files -norecurse [list [file join $root_dir rtl mlp_axi_lite.v] [file join $root_dir rtl mlp_accelerator.v] [file join $root_dir rtl params.vh]]
set_property include_dirs [list [file join $root_dir rtl]] [current_fileset]
foreach name {fc1_weight.mem fc2_weight.mem fc3_weight.mem fc1_bias.mem fc2_bias.mem fc3_bias.mem} {
    add_files -norecurse [list [file join $root_dir output fpga_mem $name]]
}
set_property top mlp_axi_lite [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir $ip_dir -vendor mnist.local -library user -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name mlp_axi_lite $core
set_property version 1.0 $core
set_property display_name {MNIST INT8 MLP Accelerator} $core
set_property description {784-128-64-10 integer MLP, pipelined MAC, AXI4-Lite pixel buffer, sticky completion and cycle counter.} $core
set_property vendor_display_name {MNIST FPGA Project} $core
set_property supported_families {zynq Production} $core
set_property core_revision 1 $core
set bus [ipx::get_bus_interfaces S_AXI -of_objects $core]
if {[llength $bus] != 1} { error "S_AXI interface was not inferred" }
set_property interface_mode slave $bus
set protocol [ipx::get_bus_parameters PROTOCOL -of_objects $bus]
if {[llength $protocol] == 0} { set protocol [ipx::add_bus_parameter PROTOCOL $bus] }
set_property value AXI4LITE $protocol
set memmap [ipx::add_memory_map S_AXI $core]
set addrblock [ipx::add_address_block Reg $memmap]
set_property base_address 0 $addrblock
set_property range 65536 $addrblock
set_property width 32 $addrblock
set_property usage register $addrblock
set_property slave_memory_map_ref S_AXI $bus
foreach {name offset access description} {
    CONTROL 0 read-write {W1 pulse: bit0 start, bit1 clear done/error, bit2 soft reset}
    STATUS 4 read-only {bit0 busy, bit1 sticky done, bit2 sticky error, bit3 image ready}
    RESULT 8 read-only {Predicted digit 0-9, valid when DONE is set}
    CYCLE_COUNT 12 read-only {Core clock cycles from accepted start to completion}
    CLOCK_HZ 16 read-only {Accelerator clock frequency}
    IMAGE_SIZE 20 read-only {784 UINT8 pixels, row-major 28x28}
    ID 24 read-only {0x4D4C5031: MLP1}
    LOADED_PIXELS 28 read-only {Number of initialized distinct pixel bytes}
    DEBUG 32 read-only {state bits2:0, layer bits9:8, neuron bits23:16}
    ERROR_CODE 36 read-only {1 busy, 2 incomplete image, 3 invalid address, 4 read-only register}
    IRQ_ENABLE 40 read-write {bit0 enables level-high sticky DONE interrupt}
} {
    set reg [ipx::add_register $name $addrblock]
    set_property address_offset $offset $reg
    set_property size 32 $reg
    set_property access $access $reg
    set_property description $description $reg
}
set statusreg [ipx::get_registers STATUS -of_objects $addrblock]
foreach {name offset} {BUSY 0 DONE 1 ERROR 2 IMAGE_READY 3} {
    set field [ipx::add_field $name $statusreg]
    set_property bit_offset $offset $field
    set_property bit_width 1 $field
    set_property access read-only $field
}
ipx::associate_bus_interfaces -busif S_AXI -clock s_axi_aclk $core
ipx::create_xgui_files $core
foreach fg [ipx::get_file_groups -of_objects $core] {
    # All imported sources/headers/data are relative to the packaged IP.
    # Do not retain an include-directory dependency on this PC's workspace.
    set_property dependency {} $fg
}
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
set memory_files {}
foreach fg [ipx::get_file_groups -of_objects $core] {
    foreach f [ipx::get_files -of_objects $fg] {
        set name [get_property name $f]
        if {[string match *.mem $name]} { lappend memory_files [file tail $name] }
    }
}
set memory_files [lsort -unique $memory_files]
if {[llength $memory_files] != 6} { error "Packaged IP must include all six .mem files: $memory_files" }
puts "IP_PACKAGED: [get_property vlnv $core]"
puts "IP_MEMORY_FILES: $memory_files"
close_project
