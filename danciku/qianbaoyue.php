<?php
/**
 * BIP39 助记词解析（稳定无报错）
 * 读取本地 bip39_en.txt 词库 | 助记词 => BIP39 Seed(64字节二进制)
 * 避开 secp256k1 椭圆曲线，彻底解决除零/hex2bin 错误
 */

// ========== 配置 ==========
$mnemonic     = "auction soon wheel inject picnic cup where popular risk safe victory atom"; // 替换为你的助记词
$wordListFile = dirname(__FILE__).'/dangciku.txt';
// =========================

// 读取本地词库
if (!file_exists($wordListFile)) {
    die("错误：找不到词库文件 {$wordListFile}");
}
$words = file($wordListFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
$words = array_map('trim', $words);

/**
 * BIP39 助记词转标准种子
 */
function bip39_mnemonic_to_seed(string $mnemonic, string $passphrase = ''): string
{
    $mnemonic = mb_convert_encoding(trim($mnemonic), 'UTF-8');
    $salt     = 'mnemonic' . mb_convert_encoding($passphrase, 'UTF-8');
    return hash_pbkdf2('sha512', $mnemonic, $salt, 2048, 64, true);
}

/**
 * 二进制转十六进制（保证偶数长度）
 */
function bin_to_hex(string $bin): string
{
    return bin2hex($bin);
}

// 主执行
try {
    $seedBin = bip39_mnemonic_to_seed($mnemonic);
    $seedHex = bin_to_hex($seedBin);

    echo "===== BIP39 解析结果 =====\n";
    echo "助记词：{$mnemonic}\n";
    echo "种子(Hex)：{$seedHex}\n";
    echo "\n";
    echo "使用说明：\n";
    echo "1. 复制上面【种子(Hex)】字符串\n";
    echo "2. 打开 BIP44 离线/在线工具，导入种子\n";
    echo "3. 选择路径 m/44'/60'/0'/0/0 导出以太坊地址 & 私钥\n";

} catch (Exception $e) {
    echo "错误：" . $e->getMessage() . "\n";
}