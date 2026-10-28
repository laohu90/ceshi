<?php
/**
 * BIP39 助记词格式校验
 * 功能：1. 检查单词数量  2. 检查单词是否在词库  3. 校验BIP39校验和
 * 依赖：仅 bcmath + 哈希扩展，不需要 gmp
 */

// 配置
function HuoQuZiLiao
  (
  
  )
{
  # return 'harbor oppose fit evil tooth scissors body shock company elbow flag add';
  $wordListFile = __DIR__ . '/dangciku.txt';

  $t_strFile = file(dirname(__FILE__).'/dangciku.txt', FILE_SKIP_EMPTY_LINES);
  while(1)
  {
    # echo $t_strFile[rand(0,2047)]; exit;
    // 待检测的完整12个助记词
    # $t_str1  = 'gallery';
    # $t_str2  = 'erase';
    # $t_str3  = 'arctic';
    # $t_str4  = 'primary';
    # $t_str5  = 'risk';
    # $t_str6  = 'wolf';
    # $t_str7  = 'ethics';
    # $t_str8  = 'high';
    # $t_str9  = 'nuclear';
    # $t_str10 = 'note';
    # $t_str11 = 'pride';
    # $t_str12 = 'mad';

    $t_str1  = trim($t_strFile[rand(0,2047)]);
    $t_str2  = trim($t_strFile[rand(0,2047)]);
    $t_str3  = trim($t_strFile[rand(0,2047)]);
    $t_str4  = trim($t_strFile[rand(0,2047)]);
    $t_str5  = trim($t_strFile[rand(0,2047)]);
    $t_str6  = trim($t_strFile[rand(0,2047)]);
    $t_str7  = trim($t_strFile[rand(0,2047)]);
    $t_str8  = trim($t_strFile[rand(0,2047)]);
    $t_str9  = trim($t_strFile[rand(0,2047)]);
    $t_str10 = trim($t_strFile[rand(0,2047)]);
    $t_str11 = trim($t_strFile[rand(0,2047)]);
    $t_str12 = trim($t_strFile[rand(0,2047)]);

    $checkMnemonic = $t_str1.' '.$t_str2.' '.$t_str3.' '.$t_str4.' '.$t_str5.' '.$t_str6.' '.$t_str7.' '.$t_str8.' '.$t_str9.' '.$t_str10.' '.$t_str11.' '.$t_str12;

    // 1. 加载BIP39词库
    $words = file($wordListFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    $wordMap = array_flip($words); // 单词=>索引，快速查询

    // 2. 分割助记词
    $mnemonicArr = explode(' ', trim($checkMnemonic));
    $count = count($mnemonicArr);

    # echo "待检测助记词：{$checkMnemonic}\n";
    # echo "单词总数：{$count}\n";

    // 规则1：12词标准助记词，数量必须是12
    if ($count !== 12) {
        echo "❌ 校验失败：单词数量不是12个\n";
        exit;
    }

    // 规则2：所有单词必须在标准词库中
    foreach ($mnemonicArr as $word) {
        if (!isset($wordMap[$word])) {
            echo "❌ 校验失败：单词【{$word}】不是标准BIP39单词\n";
            exit;
        }
    }
    # echo "✅ 所有单词均为标准BIP39单词\n";

    // 3. 校验BIP39校验和
    if (bip39Checksum($mnemonicArr, $words)) 
    {
      return $checkMnemonic; # 反回合法助记词
      # echo "✅ BIP39 校验和合法，该助记词格式完全正常\n";
      # file_put_contents(dirname(__FILE__).'/jianyanhege.txt', $checkMnemonic.PHP_EOL, FILE_APPEND);  
    } 
    else 
    {
        # echo "❌ BIP39 校验和错误，助记词拼写/顺序有误\n";
    }
  }
}











// ---------------- BIP39 校验和计算（纯PHP实现，无gmp）----------------
function bip39Checksum(array $mnemonicArr, array $wordList): bool
{
    $wordCount = count($mnemonicArr);
    $entropyBits = $wordCount * 11 - ($wordCount * 11) % 32;

    // 单词转二进制串
    $binaryStr = '';
    foreach ($mnemonicArr as $word) {
        $idx = array_search($word, $wordList);
        $binaryStr .= str_pad(decbin($idx), 11, '0', STR_PAD_LEFT);
    }

    // 截取熵值部分
    $entropy = substr($binaryStr, 0, $entropyBits);
    $entropyBytes = str_split($entropy, 8);
    $rawBytes = '';
    foreach ($entropyBytes as $byte) {
        $rawBytes .= chr(bindec($byte));
    }

    // SHA256 取前几位作为校验和
    $hash = hash('sha256', $rawBytes);
    $hashBin = '';
    for ($i = 0; $i < strlen($hash); $i++) {
        $hashBin .= str_pad(decbin(hexdec($hash[$i])), 4, '0', STR_PAD_LEFT);
    }
    $checksumBits = substr($hashBin, 0, $wordCount * 11 - $entropyBits);

    // 对比原助记词里的校验位
    $originChecksum = substr($binaryStr, $entropyBits);
    return $originChecksum === $checksumBits;
}
?>